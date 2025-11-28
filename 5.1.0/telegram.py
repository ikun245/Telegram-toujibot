# telegram_bot.py - 3.0 监听转发客户端 (AI炒群版)
# 功能: 监听转发 + AI智能炒群

from telethon.sync import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.events import NewMessage
import asyncio
import json
import os
import sys
import random
import re
from datetime import datetime, timedelta
from collections import defaultdict
from openai import AsyncOpenAI

# 用于处理媒体组的缓存和锁
media_group_cache = {}
media_group_lock = asyncio.Lock()

# 版本信息
VERSION = "3.1.0"
BANNER = f"""
╔══════════════════════════════════════════════════════════╗
║       Telegram 监听转发客户端 v{VERSION}                   ║
║       监听转发 | AI智能炒群 | 真人模拟                      ║
╚══════════════════════════════════════════════════════════╝
"""

# 获取脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'config.json')


def load_config():
    """加载配置文件"""
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "api_id": "your_api_id",
            "api_hash": "your_api_hash",
            "master_account_id": 0,
            "bot_mappings": [],
            "proxy": {
                "proxy_type": "",
                "addr": "",
                "port": 0,
                "username": "",
                "password": ""
            },
            "ai_chat": {
                "enabled": False,
                "api_key": "",
                "base_url": "https://api.deepseek. com",
                "model": "deepseek-chat",
                "chats": [],
                "reply_probability": 30,
                "min_message_length": 3,
                "context_limit": 20,
                "cooldown_seconds": 30,
                "personality": "你是一个活泼开朗的年轻人，喜欢用网络用语，说话简短有趣，偶尔会用emoji。你的回复要像真人聊天一样自然，不要太正式，可以有点调皮。回复尽量简短，一般1-2句话，最多不超过50字。不要暴露自己是AI。",
                "typing_simulation": True,
                "random_emoji": True,
            }
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=4)
        print(f"⚠️ 已创建默认配置文件 {CONFIG_FILE}，请编辑后重新运行。")
        sys.exit(1)

    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(cfg):
    """保存配置文件"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)


# 加载配置
config = load_config()

api_id = config['api_id']
api_hash = config['api_hash']
master_account_id = config['master_account_id']
bot_mappings = config.get('bot_mappings', [])
proxy_config = config.get('proxy', None)

# 确保 ai_chat 配置存在
if 'ai_chat' not in config:
    config['ai_chat'] = {
        "enabled": False,
        "api_key": "",
        "base_url": "https://api. deepseek.com",
        "model": "deepseek-chat",
        "chats": [],
        "reply_probability": 30,
        "min_message_length": 3,
        "context_limit": 20,
        "cooldown_seconds": 30,
        "personality": "你是一个活泼开朗的年轻人，喜欢用网络用语，说话简短有趣，偶尔会用emoji。你的回复要像真人聊天一样自然，不要太正式，可以有点调皮。回复尽量简短，一般1-2句话，最多不超过50字。不要暴露自己是AI。",
        "typing_simulation": True,
        "random_emoji": True,
    }
    save_config(config)

# 配置代理
proxy = None
if proxy_config and proxy_config.get('proxy_type'):
    proxy_type = proxy_config['proxy_type']
    proxy_addr = proxy_config['addr']
    proxy_port = proxy_config['port']
    proxy_username = proxy_config.get('username')
    proxy_password = proxy_config.get('password')

    if proxy_type.lower() == 'socks5':
        proxy = ('socks5', proxy_addr, proxy_port, proxy_username, proxy_password)
    elif proxy_type.lower() == 'http':
        proxy = ('http', proxy_addr, proxy_port, proxy_username, proxy_password)
    else:
        print(f"⚠️ 不支持的代理类型: {proxy_type}")
        proxy = None

# 创建客户端
client = TelegramClient(os.path.join(SCRIPT_DIR, 'anon'), api_id, api_hash, proxy=proxy)

# forwarding_map 将在 main 函数中初始化
forwarding_map = {}

# 机器人运行状态
bot_running = True


class AIChatManager:
    """AI 炒群管理器"""

    def __init__(self, cfg: dict):
        self.config = cfg
        self.client = None
        self.chat_contexts = defaultdict(list)
        self.last_reply_time = defaultdict(lambda: datetime.min)
        self.my_user_id = None

        self.emojis = ['😂', '🤣', '😊', '😄', '👍', '🔥', '💪', '😎', '🤔', '😏',
                       '🙃', '😜', '🤭', '😁', '👀', '💯', '✨', '🎉', '😋', '🥰',
                       '😤', '🤷', '😅', '🙈', '💀', '😭', '🤡', '👏', '🤝', '😌']

        self._init_client()

    def _init_client(self):
        """初始化 OpenAI 客户端"""
        ai_config = self.config.get('ai_chat', {})
        api_key = ai_config.get('api_key', '')
        base_url = ai_config.get('base_url', 'https://api.deepseek.com')

        if api_key and api_key not in ['', 'your_api_key', 'put your api key here']:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url
            )
            print("✅ AI 聊天客户端已初始化")
        else:
            self.client = None
            print("ℹ️ AI 聊天 API Key 未配置")

    def update_config(self, cfg: dict):
        """更新配置"""
        self.config = cfg
        self._init_client()

    def is_enabled(self, chat_id: int) -> bool:
        """检查是否在指定群组启用了AI聊天"""
        ai_config = self.config.get('ai_chat', {})
        if not ai_config.get('enabled', False):
            return False
        return chat_id in ai_config.get('chats', [])

    def should_reply(self, chat_id: int, message_text: str) -> bool:
        """判断是否应该回复"""
        ai_config = self.config.get('ai_chat', {})

        min_length = ai_config.get('min_message_length', 3)
        if len(message_text.strip()) < min_length:
            return False

        cooldown = ai_config.get('cooldown_seconds', 30)
        last_time = self.last_reply_time[chat_id]
        if datetime.now() - last_time < timedelta(seconds=cooldown):
            return False

        probability = ai_config.get('reply_probability', 30)
        return random.randint(1, 100) <= probability

    def add_context(self, chat_id: int, sender_name: str, message: str, is_self: bool = False):
        """添加上下文消息"""
        ai_config = self.config.get('ai_chat', {})
        context_limit = ai_config.get('context_limit', 20)

        role = "我" if is_self else sender_name
        self.chat_contexts[chat_id].append({
            'role': role,
            'content': message,
            'time': datetime.now().strftime('%H:%M')
        })

        if len(self.chat_contexts[chat_id]) > context_limit:
            self.chat_contexts[chat_id] = self.chat_contexts[chat_id][-context_limit:]

    def _add_personality(self, text: str) -> str:
        """给回复添加个性化元素"""
        ai_config = self.config.get('ai_chat', {})

        if ai_config.get('random_emoji', False) and random.random() < 0.4:
            emoji = random.choice(self.emojis)
            if random.random() < 0.5:
                text = text + emoji
            else:
                text = emoji + text

        return text

    async def generate_reply(self, chat_id: int, trigger_message: str, sender_name: str) -> str:
        """生成AI回复"""
        if not self.client:
            return None

        ai_config = self.config.get('ai_chat', {})
        personality = ai_config.get('personality', '')
        model = ai_config.get('model', 'deepseek-chat')

        context_messages = self.chat_contexts[chat_id][-15:]

        context_str = ""
        for msg in context_messages:
            context_str += f"[{msg['time']}] {msg['role']}: {msg['content']}\n"

        system_prompt = f"""{personality}

你现在在一个群聊中，以下是最近的聊天记录：
{context_str}

现在 {sender_name} 说了: "{trigger_message}"

请你根据上下文，像一个真人一样回复这条消息。要求：
1. 回复要自然、口语化，像真人聊天
2. 回复要简短，通常1-2句话，最多不超过50字
3. 可以适当使用网络用语
4. 有时候可以不直接回答问题，而是聊相关的话题
5. 偶尔可以调侃一下，但不要过分
6. 不要暴露自己是AI
7. 如果话题无聊或者你觉得没必要回复，可以回复 [SKIP] 表示跳过

只需要输出回复内容，不要加任何前缀或解释。"""

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": trigger_message}
                ],
                max_tokens=100,
                temperature=0.9,
            )

            reply = response.choices[0].message.content.strip()

            if '[SKIP]' in reply or reply == '':
                return None

            reply = reply.replace('[SKIP]', '').strip()
            reply = self._add_personality(reply)

            return reply

        except Exception as e:
            print(f"❌ AI 生成回复失败: {e}")
            return None

    async def simulate_typing(self, text: str) -> float:
        """模拟打字延迟"""
        ai_config = self.config.get('ai_chat', {})
        if not ai_config.get('typing_simulation', True):
            return 0

        base_delay = len(text) * random.uniform(0.1, 0.2)
        delay = base_delay + random.uniform(0.5, 2.0)
        return min(delay, 5.0)


# 创建 AI 聊天管理器
ai_manager = AIChatManager(config)


def update_config_file(new_bot_mappings):
    """更新配置文件"""
    global bot_mappings, forwarding_map, config
    bot_mappings = new_bot_mappings
    config['bot_mappings'] = new_bot_mappings
    save_config(config)
    print("✅ config.json 已更新！")
    asyncio.create_task(rebuild_forwarding_map())


async def rebuild_forwarding_map():
    """重新构建转发映射"""
    global forwarding_map
    forwarding_map = {}

    for mapping in bot_mappings:
        source_chat_id_from_config = mapping['source_chat']
        target_bot_username_or_id = mapping['target_bot']
        try:
            try:
                source_chat_id_processed = int(source_chat_id_from_config)
            except ValueError:
                source_chat_id_processed = source_chat_id_from_config

            source_entity = await client.get_entity(source_chat_id_processed)
            target_bot_entity = await client.get_entity(str(target_bot_username_or_id))

            peer_id_for_map = await client.get_peer_id(source_entity)
            forwarding_map[peer_id_for_map] = target_bot_entity
            print(f"✅ 映射成功: {source_chat_id_from_config} -> {target_bot_username_or_id}")
        except Exception as e:
            print(f"❌ 映射失败: {source_chat_id_from_config}, 错误: {e}")


@client.on(NewMessage())
async def handler(event):
    """消息处理器 - 转发消息 + AI炒群"""
    global bot_running

    if not bot_running:
        return

    # 转发逻辑
    if event.chat_id in forwarding_map:
        target_bot_entity = forwarding_map[event.chat_id]

        if event.message.grouped_id:
            async with media_group_lock:
                if event.message.grouped_id not in media_group_cache:
                    media_group_cache[event.message.grouped_id] = {
                        'messages': [],
                        'task': None,
                        'target_bot': target_bot_entity
                    }
                media_group_cache[event.message.grouped_id]['messages'].append(event.message.id)

                if media_group_cache[event.message.grouped_id]['task']:
                    media_group_cache[event.message.grouped_id]['task'].cancel()

                media_group_cache[event.message.grouped_id]['task'] = asyncio.create_task(
                    process_media_group(event.message.grouped_id, event.chat_id)
                )
        else:
            try:
                await client.forward_messages(target_bot_entity, event.message.id, from_peer=event.chat_id)
            except Exception as e:
                print(f"❌ 转发失败: {e}")

    # AI 炒群逻辑
    await handle_ai_chat(event)


async def handle_ai_chat(event):
    """处理 AI 炒群"""
    if not ai_manager.is_enabled(event.chat_id):
        return

    me = await client.get_me()
    if event.sender_id == me.id:
        return

    message_text = event.message.text or event.message.caption or ""
    if not message_text:
        return

    try:
        sender = await event.get_sender()
        sender_name = sender.first_name if sender else "某人"
        if hasattr(sender, 'last_name') and sender.last_name:
            sender_name += f" {sender.last_name}"
    except:
        sender_name = "某人"

    ai_manager.add_context(event.chat_id, sender_name, message_text)

    is_mentioned = False
    is_reply_to_me = False

    my_username = me.username or ""

    if my_username and f"@{my_username}" in message_text:
        is_mentioned = True

    if event.message.reply_to_msg_id:
        try:
            replied_msg = await event.message.get_reply_message()
            if replied_msg and replied_msg.sender_id == me.id:
                is_reply_to_me = True
        except:
            pass

    should_reply = False

    if is_mentioned or is_reply_to_me:
        should_reply = random.randint(1, 100) <= 90
    else:
        should_reply = ai_manager.should_reply(event.chat_id, message_text)

    if not should_reply:
        return

    reply = await ai_manager.generate_reply(event.chat_id, message_text, sender_name)

    if not reply:
        return

    typing_delay = await ai_manager.simulate_typing(reply)
    if typing_delay > 0:
        try:
            async with client.action(event.chat_id, 'typing'):
                await asyncio.sleep(typing_delay)
        except:
            await asyncio.sleep(typing_delay)

    try:
        if is_reply_to_me or (is_mentioned and random.random() < 0.7):
            await event.reply(reply)
        else:
            await client.send_message(event.chat_id, reply)

        ai_manager.last_reply_time[event.chat_id] = datetime.now()
        ai_manager.add_context(event.chat_id, "我", reply, is_self=True)

        print(f"🤖 AI回复 [{event.chat_id}]: {reply}")
    except Exception as e:
        print(f"❌ 发送AI回复失败: {e}")


async def process_media_group(grouped_id, from_peer):
    """处理媒体组"""
    await asyncio.sleep(1.5)
    async with media_group_lock:
        if grouped_id in media_group_cache:
            group_info = media_group_cache[grouped_id]
            message_ids = group_info['messages']
            target_bot = group_info['target_bot']

            try:
                await client.forward_messages(target_bot, message_ids, from_peer=from_peer)
            except Exception as e:
                print(f"❌ 媒体组转发失败: {e}")
            finally:
                del media_group_cache[grouped_id]


async def join_chat(chat_entity):
    """加入群组/频道"""
    try:
        await client(JoinChannelRequest(chat_entity))
        print(f"✅ 成功加入: {chat_entity.title}")
        return True
    except Exception as e:
        print(f"❌ 加入失败: {e}")
        return False


async def leave_chat(chat_entity):
    """退出群组/频道"""
    try:
        await client(LeaveChannelRequest(chat_entity))
        print(f"✅ 成功退出: {chat_entity.title}")
        return True
    except Exception as e:
        print(f"❌ 退出失败: {e}")
        return False


async def start_bot_interaction(bot_username):
    """向机器人发送 /start 开始交互"""
    try:
        bot_entity = await client.get_entity(bot_username)
        await client.send_message(bot_entity, '/start')
        print(f"✅ 已向 {bot_username} 发送 /start")
        return True
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False


def get_help_text():
    """获取帮助文本"""
    return """
📖 *命令帮助*

🔧 *基础命令:*
• `/help` - 显示此帮助信息
• `/status` - 查看机器人状态
• `/pause` - 暂停所有功能
• `/resume` - 恢复所有功能

🤖 *机器人交互:*
• `/start <@机器人>` - 向机器人发送 /start
• `/send <@机器人> <消息>` - 向机器人发送消息

📢 *频道管理:*
• `/join <链接或ID>` - 加入群组/频道
• `/leave <链接或ID>` - 退出群组/频道

🔗 *转发监听:*
• `/add_listen <源聊天> <@目标>` - 添加监听
• `/remove_listen <源聊天>` - 移除监听
• `/list_listen` - 列出所有监听

🤖 *AI炒群:*
• `/ai on` - 全局开启AI炒群
• `/ai off` - 全局关闭AI炒群
• `/ai add <群组ID>` - 添加炒群群组
• `/ai remove <群组ID>` - 移除炒群群组
• `/ai list` - 列出炒群群组
• `/ai prob <概率>` - 设置回复概率(0-100)
• `/ai cooldown <秒>` - 设置冷却时间
• `/ai personality <人设>` - 设置AI人设
• `/ai status` - 查看AI炒群状态
• `/ai test <消息>` - 测试AI回复
• `/ai apikey <key>` - 设置API Key
• `/ai baseurl <url>` - 设置API地址
• `/ai model <model>` - 设置模型

📊 *其他:*
• `/myid` - 获取您的用户ID
• `/chatid` - 获取聊天ID
"""


async def handle_ai_command(event, args: str):
    """处理 AI 炒群命令"""
    global config

    parts = args.strip().split(' ', 1)
    sub_cmd = parts[0].lower() if parts else ""
    sub_args = parts[1] if len(parts) > 1 else ""

    ai_config = config.get('ai_chat', {})

    if sub_cmd == 'on':
        ai_config['enabled'] = True
        config['ai_chat'] = ai_config
        save_config(config)
        ai_manager.update_config(config)
        await event.reply("✅ AI炒群已全局开启")

    elif sub_cmd == 'off':
        ai_config['enabled'] = False
        config['ai_chat'] = ai_config
        save_config(config)
        await event.reply("✅ AI炒群已全局关闭")

    elif sub_cmd == 'add':
        if not sub_args:
            await event.reply("❌ 用法: `/ai add <群组ID>`", parse_mode='Markdown')
            return
        try:
            chat_id = int(sub_args)
            if chat_id not in ai_config.get('chats', []):
                if 'chats' not in ai_config:
                    ai_config['chats'] = []
                ai_config['chats'].append(chat_id)
                config['ai_chat'] = ai_config
                save_config(config)
                ai_manager.update_config(config)
                await event.reply(f"✅ 已添加炒群群组: `{chat_id}`", parse_mode='Markdown')
            else:
                await event.reply("❌ 该群组已在列表中")
        except ValueError:
            await event.reply("❌ 请输入有效的群组ID")

    elif sub_cmd == 'remove':
        if not sub_args:
            await event.reply("❌ 用法: `/ai remove <群组ID>`", parse_mode='Markdown')
            return
        try:
            chat_id = int(sub_args)
            if chat_id in ai_config.get('chats', []):
                ai_config['chats'].remove(chat_id)
                config['ai_chat'] = ai_config
                save_config(config)
                ai_manager.update_config(config)
                await event.reply(f"✅ 已移除炒群群组: `{chat_id}`", parse_mode='Markdown')
            else:
                await event.reply("❌ 该群组不在列表中")
        except ValueError:
            await event.reply("❌ 请输入有效的群组ID")

    elif sub_cmd == 'list':
        chats = ai_config.get('chats', [])
        if chats:
            text = "🤖 *AI炒群群组列表:*\n\n"
            for i, cid in enumerate(chats, 1):
                text += f"{i}. `{cid}`\n"
            await event.reply(text, parse_mode='Markdown')
        else:
            await event.reply("📋 暂无炒群群组")

    elif sub_cmd == 'prob':
        if not sub_args:
            current = ai_config.get('reply_probability', 30)
            await event.reply(f"当前回复概率: {current}%\n用法: `/ai prob <0-100>`", parse_mode='Markdown')
            return
        try:
            prob = int(sub_args)
            if 0 <= prob <= 100:
                ai_config['reply_probability'] = prob
                config['ai_chat'] = ai_config
                save_config(config)
                await event.reply(f"✅ 回复概率已设置为: {prob}%")
            else:
                await event.reply("❌ 概率必须在 0-100 之间")
        except ValueError:
            await event.reply("❌ 请输入有效的数字")

    elif sub_cmd == 'cooldown':
        if not sub_args:
            current = ai_config.get('cooldown_seconds', 30)
            await event.reply(f"当前冷却时间: {current}秒\n用法: `/ai cooldown <秒>`", parse_mode='Markdown')
            return
        try:
            seconds = int(sub_args)
            if seconds >= 0:
                ai_config['cooldown_seconds'] = seconds
                config['ai_chat'] = ai_config
                save_config(config)
                await event.reply(f"✅ 冷却时间已设置为: {seconds}秒")
            else:
                await event.reply("❌ 冷却时间不能为负数")
        except ValueError:
            await event.reply("❌ 请输入有效的数字")

    elif sub_cmd == 'personality':
        if not sub_args:
            current = ai_config.get('personality', '未设置')
            await event.reply(f"当前人设:\n{current[:500]}...\n\n用法: `/ai personality <人设描述>`",
                              parse_mode='Markdown')
            return
        ai_config['personality'] = sub_args
        config['ai_chat'] = ai_config
        save_config(config)
        await event.reply("✅ AI人设已更新")

    elif sub_cmd == 'status':
        enabled = "✅ 开启" if ai_config.get('enabled', False) else "❌ 关闭"
        api_ok = "✅ 已配置" if ai_manager.client else "❌ 未配置"
        chats = ai_config.get('chats', [])
        prob = ai_config.get('reply_probability', 30)
        cooldown = ai_config.get('cooldown_seconds', 30)
        min_len = ai_config.get('min_message_length', 3)
        personality = ai_config.get('personality', '未设置')[:100]

        status_text = f"""
🤖 *AI炒群状态*

• 全局开关: {enabled}
• API状态: {api_ok}
• 炒群群组数: {len(chats)}
• 回复概率: {prob}%
• 冷却时间: {cooldown}秒
• 最小触发长度: {min_len}字

📝 *当前人设:*
{personality}... 
"""
        await event.reply(status_text, parse_mode='Markdown')

    elif sub_cmd == 'test':
        if not sub_args:
            await event.reply("❌ 用法: `/ai test <测试消息>`", parse_mode='Markdown')
            return

        if not ai_manager.client:
            await event.reply("❌ AI客户端未初始化，请检查API配置")
            return

        await event.reply("⏳ 正在生成回复...")

        test_chat_id = -1
        ai_manager.add_context(test_chat_id, "测试用户", "大家好啊")
        ai_manager.add_context(test_chat_id, "另一个人", "你好呀")

        reply = await ai_manager.generate_reply(test_chat_id, sub_args, "测试用户")

        if reply:
            await event.reply(f"🤖 AI回复:\n{reply}")
        else:
            await event.reply("❌ AI选择不回复或生成失败")

        ai_manager.chat_contexts[test_chat_id] = []

    elif sub_cmd == 'apikey':
        if not sub_args:
            has_key = "✅ 已配置" if ai_config.get('api_key') else "❌ 未配置"
            await event.reply(f"API Key状态: {has_key}\n用法: `/ai apikey <your_api_key>`", parse_mode='Markdown')
            return
        ai_config['api_key'] = sub_args
        config['ai_chat'] = ai_config
        save_config(config)
        ai_manager.update_config(config)
        await event.reply("✅ API Key 已更新")

    elif sub_cmd == 'baseurl':
        if not sub_args:
            current = ai_config.get('base_url', 'https://api.deepseek.com')
            await event.reply(f"当前API地址: {current}\n用法: `/ai baseurl <url>`", parse_mode='Markdown')
            return
        ai_config['base_url'] = sub_args
        config['ai_chat'] = ai_config
        save_config(config)
        ai_manager.update_config(config)
        await event.reply(f"✅ API地址已设置为: {sub_args}")

    elif sub_cmd == 'model':
        if not sub_args:
            current = ai_config.get('model', 'deepseek-chat')
            await event.reply(f"当前模型: {current}\n用法: `/ai model <model_name>`", parse_mode='Markdown')
            return
        ai_config['model'] = sub_args
        config['ai_chat'] = ai_config
        save_config(config)
        await event.reply(f"✅ 模型已设置为: {sub_args}")

    else:
        await event.reply("❌ 未知命令，使用 `/help` 查看帮助", parse_mode='Markdown')


async def main():
    """主函数"""
    global bot_running, config

    print(BANNER)

    try:
        await client.start(password=lambda: input('请输入两步验证密码 (如果没有请直接回车): '))
    except Exception as e:
        print(f"❌ 客户端启动失败: {e}")
        return

    print("✅ 客户端已启动！")
    print(f"📅 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    me = await client.get_me()
    ai_manager.my_user_id = me.id
    print(f"👤 当前账号: {me.first_name} (@{me.username}) [ID: {me.id}]")

    await rebuild_forwarding_map()
    print(f"📋 已加载 {len(forwarding_map)} 个转发映射")

    ai_status = "开启" if config.get('ai_chat', {}).get('enabled', False) else "关闭"
    ai_chats = len(config.get('ai_chat', {}).get('chats', []))
    print(f"🤖 AI炒群: {ai_status}，已配置 {ai_chats} 个群组")
    print("=" * 60)
    print("💡 机器人正在运行，等待消息...")
    print("=" * 60)

    # 处理来自主账号的命令
    @client.on(NewMessage(func=lambda e: e.is_private and e.sender_id == master_account_id))
    async def command_handler(event):
        global bot_running, config

        text = event.message.text or ""
        command = text.split(' ', 1)
        cmd = command[0].lower()
        args = command[1] if len(command) > 1 else ""

        if cmd == '/help':
            await event.reply(get_help_text(), parse_mode='Markdown')

        elif cmd == '/start':
            if not args:
                await event.reply("❌ 用法: `/start <@机器人用户名>`", parse_mode='Markdown')
                return

            bot_username = args.strip()
            if not bot_username.startswith('@'):
                bot_username = '@' + bot_username

            await event.reply(f"⏳ 正在向 {bot_username} 发送 /start...")
            success = await start_bot_interaction(bot_username)
            if success:
                await event.reply(f"✅ 已成功向 {bot_username} 发送 /start")
            else:
                await event.reply("❌ 发送失败")

        elif cmd == '/send':
            parts = args.split(' ', 1)
            if len(parts) < 2:
                await event.reply("❌ 用法: `/send <@机器人> <消息>`", parse_mode='Markdown')
                return

            bot_username = parts[0].strip()
            message_text = parts[1].strip()

            if not bot_username.startswith('@'):
                bot_username = '@' + bot_username

            try:
                bot_entity = await client.get_entity(bot_username)
                await client.send_message(bot_entity, message_text)
                await event.reply(f"✅ 已向 {bot_username} 发送消息")
            except Exception as e:
                await event.reply(f"❌ 发送失败: {e}")

        elif cmd == '/pause':
            if not bot_running:
                await event.reply("⏸️ 已经处于暂停状态")
            else:
                bot_running = False
                await event.reply("⏸️ 已暂停所有功能")

        elif cmd == '/resume':
            if bot_running:
                await event.reply("▶️ 已经在运行中")
            else:
                bot_running = True
                await event.reply("▶️ 已恢复运行")

        elif cmd == '/status':
            ai_config = config.get('ai_chat', {})
            ai_enabled = "✅ 开启" if ai_config.get('enabled', False) else "❌ 关闭"
            ai_chats_count = len(ai_config.get('chats', []))
            ai_prob = ai_config.get('reply_probability', 30)
            ai_cooldown = ai_config.get('cooldown_seconds', 30)

            status_text = f"""
📊 *机器人状态*

🔄 运行状态: {'✅ 运行中' if bot_running else '⏸️ 已暂停'}
📋 转发映射数: {len(forwarding_map)}
⏰ 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🤖 *AI炒群状态:*
• 全局开关: {ai_enabled}
• 炒群群组数: {ai_chats_count}
• 回复概率: {ai_prob}%
• 冷却时间: {ai_cooldown}秒
• API配置: {'✅' if ai_manager.client else '❌'}
"""
            await event.reply(status_text, parse_mode='Markdown')

        elif cmd == '/myid':
            await event.reply(f"👤 您的用户ID: `{event.sender_id}`", parse_mode='Markdown')

        elif cmd == '/chatid':
            if event.reply_to_msg_id:
                replied_msg = await event.get_reply_message()
                if replied_msg and replied_msg.forward:
                    fwd = replied_msg.forward
                    if fwd.chat_id:
                        await event.reply(f"💬 转发来源ID: `{fwd.chat_id}`", parse_mode='Markdown')
                    elif fwd.sender_id:
                        await event.reply(f"💬 转发来源用户ID: `{fwd.sender_id}`", parse_mode='Markdown')
                else:
                    await event.reply("❌ 请回复一条转发的消息")
            else:
                await event.reply(f"💬 当前聊天ID: `{event.chat_id}`", parse_mode='Markdown')

        elif cmd == '/join':
            if not args:
                await event.reply("❌ 用法: `/join <链接或ID>`", parse_mode='Markdown')
                return
            try:
                chat_entity = await client.get_entity(args)
                success = await join_chat(chat_entity)
                if success:
                    await event.reply(f"✅ 已加入: {chat_entity.title}")
                else:
                    await event.reply("❌ 加入失败")
            except Exception as e:
                await event.reply(f"❌ 错误: {e}")

        elif cmd == '/leave':
            if not args:
                await event.reply("❌ 用法: `/leave <链接或ID>`", parse_mode='Markdown')
                return
            try:
                chat_entity = await client.get_entity(args)
                success = await leave_chat(chat_entity)
                if success:
                    await event.reply(f"✅ 已退出: {chat_entity.title}")
                else:
                    await event.reply("❌ 退出失败")
            except Exception as e:
                await event.reply(f"❌ 错误: {e}")

        elif cmd == '/add_listen':
            parts = args.split(' ', 1)
            if len(parts) != 2:
                await event.reply("❌ 用法: `/add_listen <源聊天> <@目标>`", parse_mode='Markdown')
                return

            source_chat_arg = parts[0]
            target_bot = parts[1].strip()

            if not target_bot.startswith('@'):
                await event.reply("❌ 目标必须以 '@' 开头")
                return

            try:
                await client.get_entity(target_bot)
                existing = next((m for m in bot_mappings if str(m['source_chat']) == str(source_chat_arg)), None)

                if existing:
                    new_mappings = [m for m in bot_mappings if str(m['source_chat']) != str(source_chat_arg)]
                    new_mappings.append({'source_chat': source_chat_arg, 'target_bot': target_bot})
                    update_config_file(new_mappings)
                    await event.reply("✅ 已更新监听")
                else:
                    new_mappings = bot_mappings + [{'source_chat': source_chat_arg, 'target_bot': target_bot}]
                    update_config_file(new_mappings)
                    await event.reply("✅ 已添加监听")
            except Exception as e:
                await event.reply(f"❌ 失败: {e}")

        elif cmd == '/remove_listen':
            if not args:
                await event.reply("❌ 用法: `/remove_listen <源聊天>`", parse_mode='Markdown')
                return

            new_mappings = [m for m in bot_mappings if str(m['source_chat']) != str(args)]
            if len(new_mappings) < len(bot_mappings):
                update_config_file(new_mappings)
                await event.reply("✅ 已移除监听")
            else:
                await event.reply("❌ 未找到该监听")

        elif cmd == '/list_listen':
            if bot_mappings:
                text = "📋 *监听列表:*\n\n"
                for i, m in enumerate(bot_mappings, 1):
                    text += f"{i}. `{m['source_chat']}` → `{m['target_bot']}`\n"
                await event.reply(text, parse_mode='Markdown')
            else:
                await event.reply("📋 暂无监听配置")

        elif cmd == '/ai':
            await handle_ai_command(event, args)

    # 保持运行
    print("🚀 开始监听消息...")
    await client.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())