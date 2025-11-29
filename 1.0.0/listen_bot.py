# main. py - 1. 0.0 关键词监听提醒机器人 (优化版)
# 功能: 接收指定账号转发的消息，检测关键词并提醒用户，支持独立关键词配置、屏蔽功能

import asyncio
import logging
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional
from telegram import Update, Message
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import sqlite3

# 获取脚本所在目录
SCRIPT_DIR = os.path. dirname(os.path.abspath(__file__))

# 版本信息
VERSION = "1.0.1"
BANNER = f"""
╔══════════════════════════════════════════════════════════╗
║       Telegram 关键词监听提醒机器人 v{VERSION}              ║
║       源账号过滤 | 独立关键词 | 正则/完全匹配 | 屏蔽功能      ║
╚══════════════════════════════════════════════════════════╝
"""

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging. INFO,
    handlers=[
        logging. FileHandler(os.path.join(SCRIPT_DIR, 'keyword_bot.log'), encoding='utf-8'),
        logging. StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def escape_markdown_v2(text: str) -> str:
    """转义 MarkdownV2 特殊字符"""
    if not text:
        return ""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re. sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))


class KeywordMonitorBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder(). token(token).build()
        self.db_path = os. path.join(SCRIPT_DIR, "keyword_bot.db")
        self.config_file = os.path.join(SCRIPT_DIR, "keyword_config.json")

        self.init_database()
        self.config = self.load_config()

        self.stats = {
            'messages_received': 0,
            'keywords_matched': 0,
            'alerts_sent': 0,
            'start_time': datetime.now()
        }

        self.register_handlers()

    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS keyword_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT,
                message_text TEXT,
                source_chat_id INTEGER,
                source_chat_title TEXT,
                source_user_id INTEGER,
                source_username TEXT,
                forward_date TEXT,
                notified_admins TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def load_config(self) -> dict:
        """加载配置文件"""
        default_config = {
            "bot_token": "YOUR_BOT_TOKEN_HERE",
            "admins": [],
            "notify_users": [],
            "keywords": [],
            "allowed_senders": [],
            "user_keywords": {},
            "user_blocked": {},
            "settings": {
                "case_sensitive": False,
                "include_source_info": True,
                "max_message_length": 500,
            },
        }

        if os.path.exists(self. config_file):
            try:
                with open(self. config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                        elif isinstance(value, dict) and not key.startswith("user_"):
                            for sub_key, sub_value in value.items():
                                if sub_key not in config[key]:
                                    config[key][sub_key] = sub_value
                    return config
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
                return default_config
        else:
            self.save_config(default_config)
            return default_config

    def save_config(self, config: dict = None):
        """保存配置文件"""
        if config is None:
            config = self.config

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")

    def register_handlers(self):
        """注册消息处理器"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application. add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("getid", self.getid_command))
        self. application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("stats", self. stats_command))
        self. application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("my", self.my_keywords_panel))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(
            filters.ALL & (~filters.COMMAND),
            self.handle_message
        ))

    async def is_admin(self, user_id: int) -> bool:
        """检查用户是否为管理员"""
        return user_id in self.config. get("admins", [])

    async def is_notify_user(self, user_id: int) -> bool:
        """检查用户是否为提醒用户"""
        return user_id in self.config.get("notify_users", [])

    async def is_allowed_sender(self, user_id: int) -> bool:
        """检查是否为允许的消息发送者"""
        allowed = self.config.get("allowed_senders", [])
        if not allowed:
            return True
        return user_id in allowed

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """开始命令"""
        user_id = update. effective_user.id
        user_name = update.effective_user.full_name

        welcome_text = f"""🔍 欢迎使用关键词监听提醒机器人 v{VERSION}

👤 您的信息:
• 用户名: {user_name}
• 用户ID: {user_id}

📋 主要功能:
• 🔑 监听转发消息中的关键词
• 🎯 支持设置消息源账号
• 👤 每个用户可独立设置监听词汇
• 🔣 支持正则匹配和完全匹配
• 🚫 支持屏蔽特定发送者
• 💬 一键私聊消息发送者

🔧 使用方法:
• 使用 /my 设置您的个人监听词汇
• 管理员使用 /admin 进入管理面板

📖 输入 /help 查看所有命令"""

        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """帮助命令"""
        help_text = """📖 命令列表

🔧 基础命令:
• /start - 启动机器人
• /help - 显示此帮助信息
• /getid - 获取用户ID
• /status - 查看机器人状态
• /my - 管理个人监听词汇

⚙️ 管理命令 (仅管理员):
• /admin - 打开管理面板
• /stats - 查看匹配统计

💡 功能说明:
• 每个用户可以设置自己的监听关键词
• 支持正则表达式或完全匹配模式
• 管理员可设置允许的消息源账号
• 可以屏蔽特定发送者的消息提醒"""

        await update.message.reply_text(help_text)

    async def getid_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """获取ID命令"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        response_text = f"""🆔 ID 信息

👤 您的用户ID: {user_id}
💬 当前聊天ID: {chat_id}"""

        await update.message.reply_text(response_text)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """状态命令"""
        user_id = update.effective_user.id

        uptime = datetime.now() - self.stats['start_time']
        uptime_str = str(uptime). split('.')[0]

        is_admin = await self.is_admin(user_id)
        is_notify_user = await self.is_notify_user(user_id)

        user_keywords = self.config.get('user_keywords', {}). get(str(user_id), [])
        user_blocked = self.config.get('user_blocked', {}).get(str(user_id), [])

        status_text = f"""📊 机器人状态

🕐 运行时间: {uptime_str}
📥 接收消息: {self.stats['messages_received']}
🔑 关键词匹配: {self.stats['keywords_matched']}
🔔 发送提醒: {self. stats['alerts_sent']}

⚙️ 全局配置:
• 全局关键词数量: {len(self.config.get('keywords', []))}
• 管理员数量: {len(self.config.get('admins', []))}
• 提醒用户数: {len(self.config.get('notify_users', []))}
• 允许的源账号: {len(self.config.get('allowed_senders', []))}

👤 您的状态:
• 管理员: {'✅' if is_admin else '❌'}
• 接收提醒: {'✅' if is_notify_user else '❌'}
• 个人关键词: {len(user_keywords)} 个
• 屏蔽列表: {len(user_blocked)} 个"""

        await update.message.reply_text(status_text)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """统计命令"""
        user_id = update.effective_user.id
        if not await self.is_admin(user_id):
            await update.message.reply_text("❌ 您没有权限查看统计信息")
            return

        conn = sqlite3.connect(self. db_path)
        cursor = conn.cursor()

        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT keyword, COUNT(*) as count
            FROM keyword_logs
            WHERE DATE(timestamp) = ?
            GROUP BY keyword
            ORDER BY count DESC
            LIMIT 10
        ''', (today,))
        today_keywords = cursor.fetchall()

        cursor. execute('SELECT COUNT(*) FROM keyword_logs')
        total_matches = cursor.fetchone()[0]

        conn.close()

        stats_text = "📈 关键词匹配统计\n\n📅 今日匹配的关键词 Top 10:\n"
        if today_keywords:
            for i, (keyword, count) in enumerate(today_keywords, 1):
                stats_text += f"{i}. {keyword}: {count}次\n"
        else:
            stats_text += "暂无数据\n"

        stats_text += f"\n📊 总计:\n• 历史匹配总数: {total_matches}"

        await update.message.reply_text(stats_text)

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """管理面板"""
        user_id = update.effective_user.id
        if not await self.is_admin(user_id):
            await update. message.reply_text(
                f"❌ 您没有权限使用管理面板\n\n您的用户ID: {user_id}\n请联系管理员添加权限")
            return
        await self.send_admin_panel(update.effective_chat. id, context)

    async def my_keywords_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """个人关键词管理面板"""
        user_id = update.effective_user.id
        if not await self.is_notify_user(user_id) and not await self.is_admin(user_id):
            await update.message.reply_text(
                f"❌ 您不是提醒用户，无法设置个人关键词\n\n您的用户ID: {user_id}\n请联系管理员@添加您为提醒用户")
            return
        await self. send_my_keywords_panel(update.effective_chat.id, user_id, context)

    async def send_admin_panel(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """发送主管理面板"""
        keyboard = [
            [InlineKeyboardButton("🔑 全局关键词管理", callback_data="keyword_menu")],
            [InlineKeyboardButton("👥 用户管理", callback_data="user_menu")],
            [InlineKeyboardButton("🎯 源账号管理", callback_data="sender_menu")],
            [InlineKeyboardButton("⚙️ 设置", callback_data="settings_menu")],
            [InlineKeyboardButton("📊 查看最近匹配", callback_data="recent_matches")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚙️ 关键词监听机器人管理面板 v{VERSION}",
            reply_markup=reply_markup
        )

    async def send_my_keywords_panel(self, chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
        """发送个人关键词管理面板"""
        user_keywords = self.config.get('user_keywords', {}).get(str(user_id), [])
        user_blocked = self.config.get('user_blocked', {}).get(str(user_id), [])

        keyboard = [
            [InlineKeyboardButton("➕ 添加关键词", callback_data="my_add_keyword_select")],
            [InlineKeyboardButton(f"📋 我的关键词 ({len(user_keywords)})", callback_data="my_list_keywords")],
            [InlineKeyboardButton("➖ 删除关键词", callback_data="my_remove_keyword_prompt")],
            [InlineKeyboardButton(f"🚫 屏蔽列表 ({len(user_blocked)})", callback_data="my_list_blocked")],
            [InlineKeyboardButton("➖ 移除屏蔽", callback_data="my_remove_blocked_prompt")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text="👤 我的监听设置\n\n在这里管理您的个人监听关键词和屏蔽列表",
            reply_markup=reply_markup
        )

    async def send_keyword_menu(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """关键词管理菜单"""
        keyboard = [
            [InlineKeyboardButton("➕ 添加关键词", callback_data="add_keyword_prompt")],
            [InlineKeyboardButton("📋 列出关键词", callback_data="list_keywords")],
            [InlineKeyboardButton("➖ 删除关键词", callback_data="remove_keyword_prompt")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔑 全局关键词管理\n\n全局关键词匹配时会通知所有提醒用户",
            reply_markup=reply_markup
        )

    async def send_user_menu(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """用户管理菜单"""
        keyboard = [
            [InlineKeyboardButton("➕ 添加管理员", callback_data="add_admin_prompt")],
            [InlineKeyboardButton("📋 列出管理员", callback_data="list_admins")],
            [InlineKeyboardButton("➖ 移除管理员", callback_data="remove_admin_prompt")],
            [InlineKeyboardButton("➕ 添加提醒用户", callback_data="add_notify_user_prompt")],
            [InlineKeyboardButton("📋 列出提醒用户", callback_data="list_notify_users")],
            [InlineKeyboardButton("➖ 移除提醒用户", callback_data="remove_notify_user_prompt")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text="👥 用户管理\n\n• 管理员：可以管理机器人设置\n• 提醒用户：接收关键词匹配提醒，可设置个人关键词",
            reply_markup=reply_markup
        )

    async def send_sender_menu(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """源账号管理菜单"""
        senders_count = len(self.config.get('allowed_senders', []))

        keyboard = [
            [InlineKeyboardButton("➕ 添加源账号", callback_data="add_sender_prompt")],
            [InlineKeyboardButton(f"📋 列出源账号 ({senders_count})", callback_data="list_senders")],
            [InlineKeyboardButton("➖ 移除源账号", callback_data="remove_sender_prompt")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎯 源账号管理\n\n设置允许向机器人发送消息的账号ID\n只有来自这些账号的消息才会触发关键词检测\n\n💡 通常设置为您的 3. 0 客户端账号",
            reply_markup=reply_markup
        )

    async def send_settings_menu(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """设置菜单"""
        settings = self.config.get('settings', {})
        case_text = "🟢 开启" if settings. get('case_sensitive') else "🔴 关闭"
        source_text = "🟢 开启" if settings.get('include_source_info') else "🔴 关闭"

        keyboard = [
            [InlineKeyboardButton(f"🔤 区分大小写 ({case_text})", callback_data="toggle_case_sensitive")],
            [InlineKeyboardButton(f"📢 显示来源信息 ({source_text})", callback_data="toggle_source_info")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context. bot.send_message(chat_id=chat_id, text="⚙️ 设置", reply_markup=reply_markup)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """按钮回调处理"""
        query = update. callback_query
        await query. answer()
        user_id = query.from_user.id

        data = query.data
        chat_id = query.message.chat_id

        # 处理屏蔽按钮回调
        if data. startswith("block_"):
            block_id = data. replace("block_", "")
            await self._handle_block_user(user_id, block_id, chat_id, context)
            return

        # 处理私聊按钮回调
        if data.startswith("pm_"):
            return

        # 个人关键词管理 - 所有提醒用户都可以使用
        if data. startswith("my_"):
            if not await self.is_notify_user(user_id) and not await self.is_admin(user_id):
                await query.edit_message_text(text="❌ 您没有权限")
                return
            await self._handle_my_callback(data, user_id, chat_id, context, query)
            return

        # 管理员操作
        if not await self.is_admin(user_id):
            await query. edit_message_text(text="❌ 您没有权限")
            return

        # 菜单导航
        if data == "main_menu":
            await self. send_admin_panel(chat_id, context)
            return
        elif data == "keyword_menu":
            await self. send_keyword_menu(chat_id, context)
            context.user_data['last_menu'] = 'keyword_menu'
            return
        elif data == "user_menu":
            await self.send_user_menu(chat_id, context)
            context.user_data['last_menu'] = 'user_menu'
            return
        elif data == "sender_menu":
            await self.send_sender_menu(chat_id, context)
            context.user_data['last_menu'] = 'sender_menu'
            return
        elif data == "settings_menu":
            await self.send_settings_menu(chat_id, context)
            context.user_data['last_menu'] = 'settings_menu'
            return

        # 输入提示
        input_prompts = {
            "add_keyword_prompt": ("请发送要添加的全局关键词\n\n💡 可以一次添加多个，每行一个", "add_keyword"),
            "remove_keyword_prompt": ("请发送要删除的关键词", "remove_keyword"),
            "add_admin_prompt": ("请发送要添加的管理员用户ID", "add_admin"),
            "remove_admin_prompt": ("请发送要移除的管理员用户ID", "remove_admin"),
            "add_notify_user_prompt": ("请发送要添加的提醒用户ID", "add_notify_user"),
            "remove_notify_user_prompt": ("请发送要移除的提醒用户ID", "remove_notify_user"),
            "add_sender_prompt": ("请发送要添加的源账号ID\n\n💡 可以一次添加多个，每行一个\n这通常是您的 3.0 客户端账号ID", "add_sender"),
            "remove_sender_prompt": ("请发送要移除的源账号ID", "remove_sender"),
        }

        if data in input_prompts:
            prompt_text, action = input_prompts[data]
            await query.edit_message_text(text=prompt_text)
            context.user_data['awaiting_input'] = action
            return

        # 列表显示
        if data == "list_keywords":
            keywords = self.config.get('keywords', [])
            if not keywords:
                text = "🔑 当前没有配置全局关键词"
            else:
                text = "🔑 全局关键词列表:\n\n"
                for i, kw in enumerate(keywords, 1):
                    text += f"{i}. {kw}\n"
            await query.edit_message_text(text=text)
            return

        if data == "list_admins":
            admins = self.config.get('admins', [])
            if not admins:
                text = "👥 当前没有配置管理员"
            else:
                text = "👥 管理员列表:\n\n"
                for i, admin_id in enumerate(admins, 1):
                    text += f"{i}. {admin_id}\n"
            await query. edit_message_text(text=text)
            return

        if data == "list_notify_users":
            users = self.config.get('notify_users', [])
            if not users:
                text = "🔔 当前没有配置提醒用户"
            else:
                text = "🔔 提醒用户列表:\n\n"
                for i, uid in enumerate(users, 1):
                    text += f"{i}. {uid}\n"
            await query.edit_message_text(text=text)
            return

        if data == "list_senders":
            senders = self.config.get('allowed_senders', [])
            if not senders:
                text = "🎯 当前没有配置源账号\n\n⚠️ 未配置时将接受所有消息"
            else:
                text = "🎯 允许的源账号列表:\n\n"
                for i, sender_id in enumerate(senders, 1):
                    text += f"{i}. {sender_id}\n"
            await query.edit_message_text(text=text)
            return

        if data == "recent_matches":
            conn = sqlite3.connect(self. db_path)
            cursor = conn.cursor()
            cursor. execute('''
                SELECT keyword, source_chat_title, message_text, timestamp
                FROM keyword_logs
                ORDER BY timestamp DESC
                LIMIT 10
            ''')
            matches = cursor.fetchall()
            conn.close()

            if not matches:
                text = "📊 暂无匹配记录"
            else:
                text = "📊 最近10条匹配记录:\n\n"
                for kw, chat_title, msg_text, ts in matches:
                    msg_preview = (msg_text[:50] + '... ') if msg_text and len(msg_text) > 50 else (msg_text or '无')
                    text += f"🔑 {kw}\n"
                    text += f"📢 {chat_title or '未知'}\n"
                    text += f"💬 {msg_preview}\n\n"
            await query.edit_message_text(text=text)
            return

        # 切换开关
        if data == "toggle_case_sensitive":
            self.config['settings']['case_sensitive'] = not self.config['settings']. get('case_sensitive', False)
            self.save_config()
            status = "开启" if self.config['settings']['case_sensitive'] else "关闭"
            await query. edit_message_text(text=f"✅ 区分大小写已{status}")
        elif data == "toggle_source_info":
            self.config['settings']['include_source_info'] = not self.config['settings']. get('include_source_info', True)
            self.save_config()
            status = "开启" if self.config['settings']['include_source_info'] else "关闭"
            await query.edit_message_text(text=f"✅ 显示来源信息已{status}")

        # 刷新面板
        await self._refresh_panel(chat_id, context)

    async def _handle_my_callback(self, data: str, user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE, query):
        """处理个人关键词管理的回调"""
        user_id_str = str(user_id)

        if data == "my_add_keyword_select":
            keyboard = [
                [InlineKeyboardButton("📝 完全匹配", callback_data="my_add_exact")],
                [InlineKeyboardButton("🔣 正则匹配", callback_data="my_add_regex")],
                [InlineKeyboardButton("🔙 返回", callback_data="my_back")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="请选择匹配类型:\n\n• 完全匹配: 消息中包含该词才匹配\n• 正则匹配: 使用正则表达式匹配",
                reply_markup=reply_markup
            )
            return

        if data == "my_add_exact":
            await query.edit_message_text(text="请发送要添加的关键词 (完全匹配)\n\n💡 可以一次添加多个，每行一个")
            context.user_data['awaiting_input'] = 'my_add_keyword_exact'
            context.user_data['input_user_id'] = user_id
            return

        if data == "my_add_regex":
            await query.edit_message_text(text="请发送要添加的正则表达式\n\n💡 可以一次添加多个，每行一个\n例如: .*优惠.*|.*折扣.*")
            context. user_data['awaiting_input'] = 'my_add_keyword_regex'
            context. user_data['input_user_id'] = user_id
            return

        if data == "my_list_keywords":
            keywords = self.config.get('user_keywords', {}). get(user_id_str, [])
            if not keywords:
                text = "📋 您还没有设置个人关键词"
            else:
                text = "📋 您的关键词列表:\n\n"
                for i, kw in enumerate(keywords, 1):
                    match_type = "🔣正则" if kw.get('match_type') == 'regex' else "📝完全"
                    status = "✅" if kw.get('enabled', True) else "❌"
                    text += f"{i}. {status} {match_type} {kw['keyword']}\n"

            keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="my_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=text, reply_markup=reply_markup)
            return

        if data == "my_remove_keyword_prompt":
            await query.edit_message_text(text="请发送要删除的关键词")
            context.user_data['awaiting_input'] = 'my_remove_keyword'
            context.user_data['input_user_id'] = user_id
            return

        if data == "my_list_blocked":
            blocked = self.config.get('user_blocked', {}).get(user_id_str, [])
            if not blocked:
                text = "🚫 您的屏蔽列表为空"
            else:
                text = "🚫 您的屏蔽列表:\n\n"
                for i, bid in enumerate(blocked, 1):
                    text += f"{i}. {bid}\n"

            keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="my_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=text, reply_markup=reply_markup)
            return

        if data == "my_remove_blocked_prompt":
            await query.edit_message_text(text="请发送要移除屏蔽的ID")
            context.user_data['awaiting_input'] = 'my_remove_blocked'
            context.user_data['input_user_id'] = user_id
            return

        if data == "my_back":
            await self. send_my_keywords_panel(chat_id, user_id, context)
            return

    async def _handle_block_user(self, user_id: int, block_id: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """处理屏蔽用户"""
        user_id_str = str(user_id)

        if 'user_blocked' not in self.config:
            self.config['user_blocked'] = {}
        if user_id_str not in self. config['user_blocked']:
            self.config['user_blocked'][user_id_str] = []

        try:
            block_id_int = int(block_id)
            if block_id_int not in self.config['user_blocked'][user_id_str]:
                self.config['user_blocked'][user_id_str]. append(block_id_int)
                self.save_config()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ 已将 {block_id} 加入您的屏蔽列表\n该ID发送的消息将不再触发您的提醒"
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"ℹ️ {block_id} 已在您的屏蔽列表中"
                )
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text="❌ 无效的ID")

    async def _refresh_panel(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
        """刷新当前面板"""
        last_menu = context.user_data.get('last_menu', 'main_menu')
        if last_menu == 'keyword_menu':
            await self.send_keyword_menu(chat_id, context)
        elif last_menu == 'user_menu':
            await self.send_user_menu(chat_id, context)
        elif last_menu == 'sender_menu':
            await self.send_sender_menu(chat_id, context)
        elif last_menu == 'settings_menu':
            await self.send_settings_menu(chat_id, context)
        else:
            await self.send_admin_panel(chat_id, context)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理消息"""
        message = update.message
        if not message:
            return

        # 过滤机器人消息
        if message.from_user and message.from_user.is_bot:
            return

        user_id = message.from_user.id if message.from_user else None

        # 如果用户正在等待输入
        if user_id and context.user_data.get('awaiting_input'):
            action = context.user_data.get('awaiting_input')
            # 个人关键词设置
            if action. startswith('my_'):
                await self. handle_user_input(update, context)
                return
            # 管理员设置
            elif await self.is_admin(user_id):
                await self.handle_admin_input(update, context)
                return

        # 检查是否为允许的消息发送者
        if user_id and not await self.is_allowed_sender(user_id):
            logger.debug(f"消息来自非允许的发送者 {user_id}，跳过")
            return

        # 处理转发来的消息，检测关键词
        await self.process_forwarded_message(message)

    async def handle_user_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理普通用户输入（个人关键词设置）"""
        chat_id = update.effective_chat.id
        user_id = context.user_data.get('input_user_id', update.effective_user.id)
        user_id_str = str(user_id)
        input_text = update.message.text
        action = context.user_data.pop('awaiting_input', None)
        context.user_data. pop('input_user_id', None)

        if not action:
            return

        try:
            if action == 'my_add_keyword_exact':
                keywords = [kw.strip() for kw in input_text.split('\n') if kw.strip()]
                if 'user_keywords' not in self.config:
                    self.config['user_keywords'] = {}
                if user_id_str not in self.config['user_keywords']:
                    self.config['user_keywords'][user_id_str] = []

                added = []
                for kw in keywords:
                    exists = any(k['keyword'] == kw for k in self.config['user_keywords'][user_id_str])
                    if not exists:
                        self.config['user_keywords'][user_id_str].append({
                            'keyword': kw,
                            'match_type': 'exact',
                            'enabled': True
                        })
                        added.append(kw)

                if added:
                    self.save_config()
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ 已添加完全匹配关键词:\n" + '\n'.join(f"• {k}" for k in added)
                    )
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 关键词已存在或无效")

            elif action == 'my_add_keyword_regex':
                keywords = [kw.strip() for kw in input_text. split('\n') if kw. strip()]
                if 'user_keywords' not in self.config:
                    self.config['user_keywords'] = {}
                if user_id_str not in self.config['user_keywords']:
                    self.config['user_keywords'][user_id_str] = []

                added = []
                invalid = []
                for kw in keywords:
                    try:
                        re.compile(kw)
                        exists = any(k['keyword'] == kw for k in self.config['user_keywords'][user_id_str])
                        if not exists:
                            self.config['user_keywords'][user_id_str].append({
                                'keyword': kw,
                                'match_type': 'regex',
                                'enabled': True
                            })
                            added.append(kw)
                    except re.error:
                        invalid.append(kw)

                response = ""
                if added:
                    self.save_config()
                    response += f"✅ 已添加正则匹配关键词:\n" + '\n'. join(f"• {k}" for k in added)
                if invalid:
                    response += f"\n\n❌ 以下正则表达式无效:\n" + '\n'.join(f"• {k}" for k in invalid)
                if not added and not invalid:
                    response = "❌ 关键词已存在或无效"

                await context.bot.send_message(chat_id=chat_id, text=response)

            elif action == 'my_remove_keyword':
                kw = input_text.strip()
                if 'user_keywords' not in self.config:
                    self.config['user_keywords'] = {}
                if user_id_str not in self.config['user_keywords']:
                    self.config['user_keywords'][user_id_str] = []

                original_len = len(self.config['user_keywords'][user_id_str])
                self.config['user_keywords'][user_id_str] = [
                    k for k in self. config['user_keywords'][user_id_str] if k['keyword'] != kw
                ]

                if len(self.config['user_keywords'][user_id_str]) < original_len:
                    self.save_config()
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 已删除关键词: {kw}")
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 关键词不存在")

            elif action == 'my_remove_blocked':
                try:
                    bid = int(input_text.strip())
                    if 'user_blocked' not in self.config:
                        self.config['user_blocked'] = {}
                    if user_id_str not in self.config['user_blocked']:
                        self.config['user_blocked'][user_id_str] = []

                    if bid in self.config['user_blocked'][user_id_str]:
                        self.config['user_blocked'][user_id_str].remove(bid)
                        self.save_config()
                        await context.bot.send_message(chat_id=chat_id, text=f"✅ 已从屏蔽列表移除: {bid}")
                    else:
                        await context.bot. send_message(chat_id=chat_id, text="❌ 该ID不在屏蔽列表中")
                except ValueError:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 请输入有效的数字ID")

        except Exception as e:
            logger.error(f"处理用户输入失败: {e}")
            await context.bot.send_message(chat_id=chat_id, text=f"❌ 处理失败: {e}")
        finally:
            await self. send_my_keywords_panel(chat_id, user_id, context)

    async def handle_admin_input(self, update: Update, context: ContextTypes. DEFAULT_TYPE):
        """处理管理员输入"""
        chat_id = update. effective_chat.id
        input_text = update.message.text
        action = context.user_data. pop('awaiting_input', None)

        if not action:
            return

        try:
            if action == 'add_keyword':
                keywords = [kw.strip() for kw in input_text.split('\n') if kw.strip()]
                added = []
                for kw in keywords:
                    if kw not in self.config['keywords']:
                        self.config['keywords']. append(kw)
                        added. append(kw)
                if added:
                    self.save_config()
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 已添加关键词:\n" + '\n'.join(f"• {k}" for k in added))
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 关键词已存在或无效")

            elif action == 'remove_keyword':
                kw = input_text.strip()
                if kw in self.config['keywords']:
                    self.config['keywords'].remove(kw)
                    self. save_config()
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 已删除关键词: {kw}")
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 关键词不存在")

            elif action == 'add_admin':
                admin_id = int(input_text)
                if admin_id not in self.config['admins']:
                    self.config['admins'].append(admin_id)
                    self.save_config()
                    await context.bot. send_message(chat_id=chat_id, text=f"✅ 已添加管理员: {admin_id}")
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 该用户已是管理员")

            elif action == 'remove_admin':
                admin_id = int(input_text)
                if admin_id in self.config['admins']:
                    self.config['admins'].remove(admin_id)
                    self.save_config()
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 已移除管理员: {admin_id}")
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 该用户不是管理员")

            elif action == 'add_notify_user':
                uid = int(input_text)
                if uid not in self.config['notify_users']:
                    self.config['notify_users']. append(uid)
                    self.save_config()
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 已添加提醒用户: {uid}")
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 该用户已在提醒列表中")

            elif action == 'remove_notify_user':
                uid = int(input_text)
                if uid in self.config['notify_users']:
                    self. config['notify_users'].remove(uid)
                    self.save_config()
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 已移除提醒用户: {uid}")
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 该用户不在提醒列表中")

            elif action == 'add_sender':
                senders = [s.strip() for s in input_text.split('\n') if s.strip()]
                added = []
                for s in senders:
                    try:
                        sender_id = int(s)
                        if sender_id not in self.config['allowed_senders']:
                            self.config['allowed_senders']. append(sender_id)
                            added.append(sender_id)
                    except ValueError:
                        pass
                if added:
                    self.save_config()
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ 已添加源账号:\n" + '\n'.join(f"• {s}" for s in added)
                    )
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ 账号已存在或格式无效")

            elif action == 'remove_sender':
                try:
                    sender_id = int(input_text. strip())
                    if sender_id in self.config['allowed_senders']:
                        self. config['allowed_senders'].remove(sender_id)
                        self.save_config()
                        await context.bot.send_message(chat_id=chat_id, text=f"✅ 已移除源账号: {sender_id}")
                    else:
                        await context.bot.send_message(chat_id=chat_id, text="❌ 该账号不在列表中")
                except ValueError:
                    await context.bot. send_message(chat_id=chat_id, text="❌ 请输入有效的数字ID")

        except ValueError:
            await context.bot. send_message(chat_id=chat_id, text="❌ 输入格式错误")
        except Exception as e:
            logger. error(f"处理管理员输入失败: {e}")
            await context.bot. send_message(chat_id=chat_id, text=f"❌ 处理失败: {e}")
        finally:
            await self._refresh_panel(chat_id, context)

    async def process_forwarded_message(self, message: Message):
        """处理转发的消息，检测关键词"""
        self.stats['messages_received'] += 1

        # 过滤机器人消息
        if message.from_user and message.from_user.is_bot:
            logger.debug("跳过机器人消息")
            return

        # 获取消息文本
        text = message.text or message.caption or ""
        if not text:
            return

        # 获取来源信息
        source_info = self._extract_source_info(message)

        # 检测关键词
        matched_results = self._check_all_keywords(text, source_info)

        if matched_results:
            self.stats['keywords_matched'] += len(matched_results)
            logger.info(f"检测到关键词匹配: {len(matched_results)} 个用户")
            await self._send_alerts(message, text, matched_results, source_info)

    def _extract_source_info(self, message: Message) -> dict:
        """提取消息来源信息"""
        info = {
            'chat_id': None,
            'chat_title': None,
            'chat_username': None,
            'chat_type': None,
            'user_id': None,
            'user_name': None,
            'username': None,
            'sender_name': None,
            'forward_date': None,
            'message_id': message.message_id,
        }

        if hasattr(message, 'forward_origin') and message.forward_origin:
            origin = message.forward_origin
            origin_type = type(origin).__name__

            if origin_type == 'MessageOriginChannel':
                if hasattr(origin, 'chat'):
                    info['chat_id'] = origin.chat.id
                    info['chat_title'] = origin.chat.title
                    info['chat_username'] = getattr(origin.chat, 'username', None)
                    info['chat_type'] = origin. chat.type

            elif origin_type == 'MessageOriginUser':
                if hasattr(origin, 'sender_user'):
                    info['user_id'] = origin.sender_user.id
                    info['user_name'] = origin.sender_user.full_name
                    info['username'] = getattr(origin.sender_user, 'username', None)

            elif origin_type == 'MessageOriginHiddenUser':
                if hasattr(origin, 'sender_user_name'):
                    info['sender_name'] = origin.sender_user_name

            elif origin_type == 'MessageOriginChat':
                if hasattr(origin, 'sender_chat'):
                    info['chat_id'] = origin.sender_chat.id
                    info['chat_title'] = origin. sender_chat.title
                    info['chat_username'] = getattr(origin.sender_chat, 'username', None)
                    info['chat_type'] = origin.sender_chat.type

        else:
            if hasattr(message, 'forward_from_chat') and message.forward_from_chat:
                chat = message.forward_from_chat
                info['chat_id'] = chat.id
                info['chat_title'] = chat.title
                info['chat_username'] = getattr(chat, 'username', None)
                info['chat_type'] = chat.type

            if hasattr(message, 'forward_from') and message.forward_from:
                user = message.forward_from
                info['user_id'] = user.id
                info['user_name'] = user.full_name
                info['username'] = getattr(user, 'username', None)

            if hasattr(message, 'forward_sender_name') and message.forward_sender_name:
                info['sender_name'] = message.forward_sender_name

        return info

    def _check_all_keywords(self, text: str, source_info: dict) -> Dict[int, List[str]]:
        """检查所有关键词（全局 + 用户个人），返回 {user_id: [matched_keywords]}"""
        matched_results = {}
        settings = self.config. get('settings', {})
        case_sensitive = settings.get('case_sensitive', False)

        check_text = text if case_sensitive else text.lower()
        source_id = source_info. get('chat_id') or source_info.get('user_id')

        # 检查全局关键词，通知所有提醒用户
        global_matched = []
        for keyword in self.config. get('keywords', []):
            check_keyword = keyword if case_sensitive else keyword.lower()
            if check_keyword in check_text:
                global_matched.append(keyword)

        if global_matched:
            for uid in self.config. get('notify_users', []):
                user_blocked = self.config.get('user_blocked', {}).get(str(uid), [])
                if source_id and source_id in user_blocked:
                    continue
                if uid not in matched_results:
                    matched_results[uid] = []
                matched_results[uid]. extend(global_matched)

        # 检查每个用户的个人关键词
        for uid_str, user_kw_list in self.config.get('user_keywords', {}).items():
            try:
                uid = int(uid_str)
            except ValueError:
                continue

            user_blocked = self.config.get('user_blocked', {}).get(uid_str, [])
            if source_id and source_id in user_blocked:
                continue

            for kw_config in user_kw_list:
                if not kw_config.get('enabled', True):
                    continue

                keyword = kw_config['keyword']
                match_type = kw_config. get('match_type', 'exact')

                matched = False
                if match_type == 'regex':
                    try:
                        pattern = keyword if case_sensitive else keyword
                        flags = 0 if case_sensitive else re.IGNORECASE
                        if re.search(pattern, text, flags):
                            matched = True
                    except re.error:
                        pass
                else:
                    check_keyword = keyword if case_sensitive else keyword.lower()
                    if check_keyword in check_text:
                        matched = True

                if matched:
                    if uid not in matched_results:
                        matched_results[uid] = []
                    if keyword not in matched_results[uid]:
                        matched_results[uid].append(keyword)

        return matched_results

    async def _send_alerts(self, message: Message, text: str, matched_results: Dict[int, List[str]], source_info: dict):
        """发送提醒"""
        settings = self.config.get('settings', {})
        max_length = settings.get('max_message_length', 500)

        text_preview = text[:max_length] + '...' if len(text) > max_length else text

        source_id = source_info.get('chat_id') or source_info. get('user_id')

        for uid, keywords in matched_results.items():
            try:
                # 构建提醒消息
                alert_text = f"🔔 关键词匹配提醒\n\n"
                alert_text += f"🔑 匹配关键词: {', '.join(keywords)}\n\n"
                alert_text += f"💬 消息内容:\n{text_preview}"

                # 添加来源信息
                if settings.get('include_source_info', True):
                    alert_text += "\n\n📢 来源信息:"

                    if source_info.get('chat_title'):
                        alert_text += f"\n• 频道/群组: {source_info['chat_title']}"
                    if source_info.get('chat_id'):
                        alert_text += f"\n• 频道ID: {source_info['chat_id']}"
                    if source_info.get('chat_username'):
                        alert_text += f"\n• 频道用户名: @{source_info['chat_username']}"

                    if source_info.get('user_name'):
                        alert_text += f"\n• 发送者: {source_info['user_name']}"
                    if source_info.get('user_id'):
                        alert_text += f"\n• 用户ID: {source_info['user_id']}"
                    if source_info.get('username'):
                        alert_text += f"\n• 用户名: @{source_info['username']}"
                    if source_info.get('sender_name') and not source_info.get('user_id'):
                        alert_text += f"\n• 发送者: {source_info['sender_name']} (隐藏)"

                # 构建按钮
                buttons = []

                # 私聊按钮
                if source_info.get('username'):
                    buttons.append(InlineKeyboardButton("💬 私聊", url=f"https://t.me/{source_info['username']}"))
                elif source_info.get('user_id'):
                    buttons. append(InlineKeyboardButton("💬 私聊", url=f"tg://user?id={source_info['user_id']}"))

                # 屏蔽按钮
                if source_id:
                    buttons.append(InlineKeyboardButton("🚫 屏蔽", callback_data=f"block_{source_id}"))

                reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None

                await self.application.bot.send_message(
                    chat_id=uid,
                    text=alert_text,
                    reply_markup=reply_markup
                )
                self.stats['alerts_sent'] += 1
                logger.info(f"已发送关键词提醒到用户 {uid}")

            except Exception as e:
                logger.error(f"发送提醒到用户 {uid} 失败: {e}")

        # 记录日志
        self._log_match(matched_results, text, source_info)

    def _log_match(self, matched_results: Dict[int, List[str]], text: str, source_info: dict):
        """记录匹配日志"""
        try:
            conn = sqlite3.connect(self. db_path)
            cursor = conn.cursor()

            all_keywords = set()
            for keywords in matched_results.values():
                all_keywords.update(keywords)

            for keyword in all_keywords:
                cursor.execute('''
                    INSERT INTO keyword_logs 
                    (keyword, message_text, source_chat_id, source_chat_title, 
                     source_user_id, source_username, forward_date, notified_admins)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    keyword,
                    text[:1000],
                    source_info.get('chat_id'),
                    source_info.get('chat_title'),
                    source_info.get('user_id'),
                    source_info.get('username'),
                    source_info.get('forward_date'),
                    json.dumps(list(matched_results.keys()))
                ))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"记录匹配日志失败: {e}")

    def run(self):
        """运行机器人"""
        print(BANNER)
        logger.info("关键词监听机器人启动中...")
        self.application.run_polling()


if __name__ == "__main__":
    script_dir = os.path.dirname(os. path.abspath(__file__))
    config_file = os. path.join(script_dir, "keyword_config.json")

    print(f"📁 脚本目录: {script_dir}")
    print(f"📁 配置文件: {config_file}")

    TOKEN = None

    if not os.path.exists(config_file):
        print(f"❌ 配置文件不存在，正在创建默认配置...")
        default_config = {
            "bot_token": "YOUR_BOT_TOKEN_HERE",
            "admins": [],
            "notify_users": [],
            "keywords": [],
            "allowed_senders": [],
            "user_keywords": {},
            "user_blocked": {},
            "settings": {
                "case_sensitive": False,
                "include_source_info": True,
                "max_message_length": 500
            }
        }
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, ensure_ascii=False, indent=2)
        print(f"✅ 已创建配置文件，请编辑后重新运行")
        exit(1)

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            TOKEN = config_data.get("bot_token")
    except Exception as e:
        print(f"❌ 加载配置文件失败: {e}")
        exit(1)

    invalid_tokens = ["YOUR_BOT_TOKEN_HERE", "your_bot_token", ""]
    if not TOKEN or TOKEN in invalid_tokens:
        print(f"❌ 请在配置文件中设置有效的 bot_token")
        exit(1)

    print(f"✅ Token 加载成功: {TOKEN[:20]}...")

    bot = KeywordMonitorBot(TOKEN)
    bot.run()
