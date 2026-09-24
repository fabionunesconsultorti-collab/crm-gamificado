import json
import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from app.tasks.buffer import (
    add_to_buffer,
    is_valid_batch,
    pop_all_buffered_messages,
    REDIS_PREFIX_BUFFER,
    REDIS_PREFIX_TIMER
)
from app.utils.conversation_memory import ConversationMemory
from app.tasks.whatsapp import process_buffered_whatsapp_messages


class MockRedis:
    def __init__(self):
        self.store = {}
        self.lists = {}

    def rpush(self, key, *values):
        if key not in self.lists:
            self.lists[key] = []
        for v in values:
            self.lists[key].append(v)
        return len(self.lists[key])

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if end == -1:
            end = len(items)
        else:
            end = end + 1
        return items[start:end]

    def ltrim(self, key, start, stop):
        items = self.lists.get(key, [])
        if stop == -1:
            self.lists[key] = items[start:]
        else:
            self.lists[key] = items[start:stop + 1]

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                count += 1
            if k in self.lists:
                del self.lists[k]
                count += 1
        return count

    def expire(self, key, ttl):
        return True

    def pipeline(self):
        return MockPipeline(self)


class MockPipeline:
    def __init__(self, redis_instance):
        self.redis = redis_instance
        self.commands = []

    def rpush(self, key, *values):
        self.commands.append(('rpush', key, values))
        return self

    def expire(self, key, ttl):
        self.commands.append(('expire', key, ttl))
        return self

    def set(self, key, value, ex=None, nx=False):
        self.commands.append(('set', key, value, ex, nx))
        return self

    def lrange(self, key, start, end):
        self.commands.append(('lrange', key, start, end))
        return self

    def delete(self, *keys):
        self.commands.append(('delete', keys))
        return self

    def ltrim(self, key, start, stop):
        self.commands.append(('ltrim', key, start, stop))
        return self

    def execute(self):
        results = []
        for cmd in self.commands:
            op = cmd[0]
            if op == 'rpush':
                results.append(self.redis.rpush(cmd[1], *cmd[2]))
            elif op == 'expire':
                results.append(self.redis.expire(cmd[1], cmd[2]))
            elif op == 'set':
                results.append(self.redis.set(cmd[1], cmd[2], ex=cmd[3], nx=cmd[4]))
            elif op == 'lrange':
                results.append(self.redis.lrange(cmd[1], cmd[2], cmd[3]))
            elif op == 'delete':
                results.append(self.redis.delete(*cmd[1]))
            elif op == 'ltrim':
                results.append(self.redis.ltrim(cmd[1], cmd[2], cmd[3]))
        self.commands = []
        return results


from config import TestConfig

class WhatsAppBufferTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()
        from app import db
        db.create_all()

    def tearDown(self):
        from app import db
        db.session.remove()
        self.app_ctx.pop()


    def test_buffer_push_and_pop(self):
        mock_redis = MockRedis()
        with patch('app.tasks.buffer.get_redis_connection', return_value=mock_redis), \
             patch('app.tasks.buffer.get_queue') as mock_get_queue:
            
            mock_queue = MagicMock()
            mock_get_queue.return_value = mock_queue

            chat_id = "5511999999999@c.us"
            token1, delay1 = add_to_buffer(chat_id, {"id": "msg-1", "body": "Olá"})
            token2, delay2 = add_to_buffer(chat_id, {"id": "msg-2", "body": "Tudo bem?"})

            self.assertFalse(is_valid_batch(chat_id, token1))
            self.assertTrue(is_valid_batch(chat_id, token2))

            messages = pop_all_buffered_messages(chat_id)
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]['body'], "Olá")
            self.assertEqual(messages[1]['body'], "Tudo bem?")

            # Após pop, o buffer deve estar vazio
            self.assertEqual(len(pop_all_buffered_messages(chat_id)), 0)

    def test_conversation_memory(self):
        mock_redis = MockRedis()
        with patch('app.utils.conversation_memory.get_redis_connection', return_value=mock_redis):
            chat_id = "5511988887777@c.us"

            ConversationMemory.record_turn(chat_id, "Quanto custa o CRM?", "Custa R$ 149/mês.")
            ConversationMemory.record_turn(chat_id, "Tem teste grátis?", "Sim, temos 7 dias de teste.")

            history = ConversationMemory.get_context_messages(chat_id)
            self.assertEqual(len(history), 4)
            self.assertEqual(history[0], {"role": "user", "content": "Quanto custa o CRM?"})
            self.assertEqual(history[1], {"role": "assistant", "content": "Custa R$ 149/mês."})
            self.assertEqual(history[2], {"role": "user", "content": "Tem teste grátis?"})
            self.assertEqual(history[3], {"role": "assistant", "content": "Sim, temos 7 dias de teste."})

    def test_process_buffered_whatsapp_messages(self):
        mock_redis = MockRedis()
        chat_id = "5511977776666@c.us"
        token = "test-token-123"

        mock_redis.set(f"{REDIS_PREFIX_TIMER}:{chat_id}", token)
        mock_redis.rpush(
            f"{REDIS_PREFIX_BUFFER}:{chat_id}",
            json.dumps({"id": "m1", "body": "Oi"}),
            json.dumps({"id": "m2", "body": "Gostaria de ver uma demo"})
        )

        with patch('app.tasks.buffer.get_redis_connection', return_value=mock_redis), \
             patch('app.utils.conversation_memory.get_redis_connection', return_value=mock_redis), \
             patch('app.utils.waha.WahaAPI.send_seen', return_value=(True, "ok")) as mock_seen, \
             patch('app.utils.waha.WahaAPI.start_typing', return_value=(True, "ok")) as mock_typing, \
             patch('app.utils.waha.WahaAPI.stop_typing', return_value=(True, "ok")) as mock_stop_typing, \
             patch('app.utils.waha.WahaAPI.send_text', return_value=(True, {"id": "resp-1"})) as mock_send, \
             patch('app.utils.ai_handler.AIHandler.generate_chat_reply', return_value=("Claro! Vamos agendar uma demonstração.", None)) as mock_ai:


            res = process_buffered_whatsapp_messages(chat_id, token)

            self.assertEqual(res['status'], "completed")
            self.assertEqual(res['batch_size'], 2)
            self.assertTrue(res['sent'])
            self.assertEqual(res['reply'], "Claro! Vamos agendar uma demonstração.")

            # Verifica se o método unificado da IA recebeu o texto concatenado
            mock_ai.assert_called_once()
            args, kwargs = mock_ai.call_args
            self.assertEqual(kwargs['customer_message'], "Oi\nGostaria de ver uma demo")

            # Verifica chamadas WAHA
            mock_seen.assert_called_once()
            mock_typing.assert_called_once()
            mock_stop_typing.assert_called_once()
            mock_send.assert_called_once_with(chat_id, "Claro! Vamos agendar uma demonstração.", instance_id=None)


if __name__ == '__main__':
    unittest.main()
