from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.agent.message import TextPart
import importlib
import inspect
import datetime
import zoneinfo

@register("helloworld", "YourName", "一个简单的 Hello World 插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._original_append_system_reminders = None
        self._patched_module = None

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        # Monkey patch _append_system_reminders (note: it's a function, not a method)
        try:
            # Import the module containing the function
            module = importlib.import_module('astrbot.core.astr_main_agent')
            self._patched_module = module
            
            # Save the original function
            if hasattr(module, '_append_system_reminders'):
                self._original_append_system_reminders = module._append_system_reminders
                
                # Create a wrapper function
                def patched_function(event, req, cfg, timezone):
                    system_parts: list[str] = []
                    if cfg.get("identifier"):
                        user_id = event.message_obj.sender.user_id
                        user_nickname = event.message_obj.sender.nickname
                        if event.role:
                            system_parts.append(f"User ID: {user_id}, Nickname: {user_nickname}, Role: {event.role}")
                        else:
                            system_parts.append(f"User ID: {user_id}, Nickname: {user_nickname}")

                    if cfg.get("group_name_display") and event.message_obj.group_id:
                        if not event.message_obj.group:
                            logger.error(
                                "Group name display enabled but group object is None. Group ID: %s",
                                event.message_obj.group_id,
                            )
                        else:
                            group_name = event.message_obj.group.group_name
                            if group_name:
                                system_parts.append(f"Group name: {group_name}")

                    if cfg.get("datetime_system_prompt"):
                        current_time = None
                        if timezone:
                            try:
                                now = datetime.datetime.now(zoneinfo.ZoneInfo(timezone))
                                current_time = now.strftime("%Y-%m-%d %H:%M (%Z)")
                            except Exception as exc:  # noqa: BLE001
                                logger.error("时区设置错误: %s, 使用本地时区", exc)
                        if not current_time:
                            current_time = (
                                datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M (%Z)")
                            )
                        system_parts.append(f"Current datetime: {current_time}")

                    if system_parts:
                        system_content = (
                            "<system_reminder>" + "\n".join(system_parts) + "</system_reminder>"
                        )
                        req.extra_user_content_parts.append(TextPart(text=system_content))
                
                # Replace the function in the module
                module._append_system_reminders = patched_function
                logger.info("Successfully patched _append_system_reminders")
            else:
                logger.warning("Could not find _append_system_reminders function in module")
                return
            
        except Exception as e:
            logger.error(f"Failed to monkey patch _append_system_reminders: {e}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        # Restore the original function
        if self._patched_module is not None and self._original_append_system_reminders is not None:
            self._patched_module._append_system_reminders = self._original_append_system_reminders
            logger.info("Restored original _append_system_reminders")
