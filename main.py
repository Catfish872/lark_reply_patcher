# lark_final_patcher_v17_stable.py (The final, syntactically correct, and logically sound version)
# Description: 修正了致命的SyntaxError，并保留了所有经过验证的健壮性设计。

import json
import asyncio
import base64
from astrbot.api.star import Context, register, Star
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
import astrbot.api.message_components as Comp

try:
    from lark_oapi.api.im.v1 import GetMessageRequest, GetMessageResourceRequest
    from lark_oapi.api.contact.v3 import GetUserRequest
    LARK_OAPI_AVAILABLE = True
except ImportError:
    LARK_OAPI_AVAILABLE = False

original_handle_msg = None

async def _new_handle_msg(self, abm: "AstrBotMessage"):
    """
    这是最终的增强版 handle_msg。
    它通过幂等性检查避免重复处理，并干净地处理文本和图片引用。
    """
    # ==================== 核心修正：将 global 声明移到函数顶部 ====================
    global original_handle_msg

    try:
        # 幂等性检查：如果消息已经处理过，直接调用原始方法并返回
        if hasattr(abm, 'lark_patcher_processed') and abm.lark_patcher_processed:
            logger.debug("[Final Patcher] 检测到消息已被处理，跳过。")
            if original_handle_msg: await original_handle_msg(self, abm)
            return
        
        raw_message = abm.raw_message
        parent_id = raw_message.parent_id

        if parent_id:
            logger.debug(f"[Final Patcher] 检测到回复消息，parent_id: {parent_id}。")
            msg_req = GetMessageRequest.builder().message_id(parent_id).build()
            msg_res = await self.lark_api.im.v1.message.aget(msg_req)

            if msg_res.success() and msg_res.data.items:
                replied_item = msg_res.data.items[0]
                replied_msg_type = replied_item.msg_type
                
                if replied_msg_type in ('text', 'post'):
                    sender_obj = replied_item.sender
                    if isinstance(sender_obj, str): replied_sender_id = sender_obj
                    else: replied_sender_id = sender_obj.id
                    replied_text = _parse_lark_content_to_plain_text(replied_item.body.content)
                    replied_sender_name = replied_sender_id
                    try:
                        user_req = GetUserRequest.builder().user_id_type("open_id").user_id(replied_sender_id).build()
                        user_res = await self.lark_api.contact.v3.user.aget(user_req)
                        if user_res.success(): replied_sender_name = user_res.data.user.name
                    except Exception: pass
                    reply_prefix = f"[引用消息:{replied_sender_name}:{replied_text}]"
                    body_text = abm.message_str
                    final_text = f"{reply_prefix}{body_text}"
                    abm.message_str = final_text
                    abm.message = [comp for comp in abm.message if not isinstance(comp, Comp.Plain)]
                    abm.message.append(Comp.Plain(final_text))
                    logger.info(f"[Final Patcher] 成功拼接文本回复上下文。")

                elif replied_msg_type == 'image':
                    content_data = json.loads(replied_item.body.content)
                    image_key = content_data.get('image_key')
                    if image_key:
                        resource_req = GetMessageResourceRequest.builder().message_id(parent_id).file_key(image_key).type("image").build()
                        resource_res = await self.lark_api.im.v1.message_resource.aget(resource_req)
                        if resource_res.success():
                            image_bytes = resource_res.file.read()
                            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                            image_component = Comp.Image.fromBase64(image_base64)
                            abm.message.insert(0, image_component)
                            logger.info("[Final Patcher] 成功注入引用的图片到消息链。")
        
        # 标记此消息已被处理
        abm.lark_patcher_processed = True

    except Exception as e:
        logger.error(f"[Final Patcher] 在修正上下文中发生错误: {e}", exc_info=True)
    
    # 无论如何，都调用原始的 handle_msg 方法
    if original_handle_msg:
        await original_handle_msg(self, abm)

def _parse_lark_content_to_plain_text(content_json_string: str) -> str:
    if not content_json_string: return "[空内容]"
    try:
        data = json.loads(content_json_string)
        if 'text' in data: return data['text'].strip()
        if 'content' in data:
            text_parts = [data['title'].strip()] if data.get('title') else []
            for block in data.get('content', []):
                for element in block:
                    if element.get('tag') == 'text' and element.get('text'):
                        text_parts.append(element['text'].strip())
            return " ".join([part for part in text_parts if part]) or "[富文本中无文字]"
        return "[非文本内容]"
    except: return "[内容解析失败]"

@register(
    "lark_final_patcher",
    "Gemini",
    "通过猴子补丁从源头修正Lark适配器的回复处理逻辑（支持文本和图片）",
    "17.0.0-stable",
)
class LarkFinalPatcher(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.is_patched = False
        self.patch_lock = asyncio.Lock()
        if LARK_OAPI_AVAILABLE:
            logger.info("[Final Patcher] 插件已加载，准备在第一个Lark事件到达时应用补丁...")
        else:
            logger.error("[Final Patcher] 关键组件 'lark-oapi' 未安装，插件无法工作！")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        await self._apply_patch_on_first_event(event)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        await self._apply_patch_on_first_event(event)

    async def _apply_patch_on_first_event(self, event: AstrMessageEvent):
        if self.is_patched or event.get_platform_name() != 'lark':
            return
        async with self.patch_lock:
            if self.is_patched: return
            logger.info("[Final Patcher] 检测到第一个Lark事件，开始应用猴子补丁...")
            global original_handle_msg
            try:
                platform_instance = self.context.get_platform(event.get_platform_name())
                if not platform_instance:
                    logger.error(f"[Final Patcher] 无法从上下文中找到平台 '{event.get_platform_name()}' 的实例！")
                    return
                AdapterClass = platform_instance.__class__
                original_handle_msg = AdapterClass.handle_msg
                AdapterClass.handle_msg = _new_handle_msg
                self.is_patched = True
                logger.info(f"[Final Patcher] 成功！'{AdapterClass.__name__}' 的 handle_msg 逻辑已被增强以支持多模态。")
            except Exception as e:
                logger.error(f"[Final Patcher] 应用补丁时发生致命错误: {e}", exc_info=True)

    async def terminate(self):
        global original_handle_msg
        if self.is_patched and original_handle_msg is not None:
            if self.context and hasattr(self.context, 'platforms'):
                for p in self.context.platforms.values():
                    if p.__class__.__name__ == 'LarkPlatformAdapter':
                        p.__class__.handle_msg = original_handle_msg
                        logger.info("[Final Patcher] 插件已停用，Lark适配器已尝试恢复原始行为。")
                        break