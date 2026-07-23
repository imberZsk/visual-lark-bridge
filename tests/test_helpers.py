"""桥接测试共用的 Claude 假会话与记录型应用。"""

import threading

from lark_ai_bridge import (
    BridgeApp,
)


class FakeClaudeSession:
    """测试用 Claude 会话，记录输入并返回确定性回复。"""

    def __init__(
        self, workspace, log_dir, system_prompt, timeout, session_id=None, resume=False
    ):
        """初始化假会话，参数与真实 ClaudeInteractiveSession 保持一致。"""
        # workspace 存储测试传入的任务工作目录。
        self.workspace = workspace
        # log_dir 存储测试传入的任务日志目录。
        self.log_dir = log_dir
        # system_prompt 存储测试传入的系统提示。
        self.system_prompt = system_prompt
        # timeout 存储测试传入的超时时间。
        self.timeout = timeout
        # session_id 存储测试传入的会话 ID；持久化恢复时会带上历史 ID，未传则生成一个占位值。
        self.session_id = session_id or "fake-session-id"
        # resume 记录本次是否按恢复模式启动，供断言持久化续接逻辑使用。
        self.resume = resume
        # started 记录 start 是否被调用。
        self.started = False
        # stopped 记录 stop 是否被调用。
        self.stopped = False
        # questions 存储所有 ask 收到的问题文本。
        self.questions = []

    def start(self):
        """记录测试会话已启动。"""
        self.started = True

    def stop(self):
        """记录测试会话已停止。"""
        self.stopped = True

    def ask(self, message):
        """返回可预测的测试回答。"""
        self.questions.append(message)
        return f"回复:{message}"


class RecordingBridgeApp(BridgeApp):
    """测试用桥接应用，记录飞书发送和编辑动作而不调用 lark-cli。"""

    def __init__(self, args):
        """初始化记录型桥接应用，args 与真实 BridgeApp 保持一致。"""
        super().__init__(args)
        # sent_replies 存储桥接尝试发送的飞书回复。
        self.sent_replies = []
        # updated_messages 存储桥接尝试编辑的飞书消息。
        self.updated_messages = []

    def _send_reply(self, message_id, text):
        """记录一次飞书回复，并返回可被后续编辑的模拟消息 ID。"""
        self.sent_replies.append((message_id, text))
        return "om_processing"

    def _update_message(self, message_id, text):
        """记录一次飞书消息编辑，并返回成功。"""
        self.updated_messages.append((message_id, text))
        return True


class BlockingClaudeSession:
    """测试用阻塞 Claude 会话，用来模拟长时间执行中的任务。"""

    # started 在 ask 进入阻塞等待时置位，测试用它确认后台任务已开始。
    started = threading.Event()
    # release 在测试允许长任务结束时置位，避免测试依赖真实耗时。
    release = threading.Event()

    @classmethod
    def reset(cls):
        """重置类级同步事件，确保不同测试之间互不影响。"""
        cls.started = threading.Event()
        cls.release = threading.Event()

    def __init__(
        self, workspace, log_dir, system_prompt, timeout, session_id=None, resume=False
    ):
        """初始化阻塞会话，参数与真实 ClaudeInteractiveSession 保持一致。"""
        # workspace 存储测试传入的任务工作目录。
        self.workspace = workspace
        # log_dir 存储测试传入的任务日志目录。
        self.log_dir = log_dir
        # system_prompt 存储测试传入的系统提示。
        self.system_prompt = system_prompt
        # timeout 存储测试传入的超时时间。
        self.timeout = timeout
        # session_id 存储测试传入的会话 ID；持久化恢复时会带上历史 ID，未传则生成一个占位值。
        self.session_id = session_id or "fake-session-id"
        # resume 记录本次是否按恢复模式启动。
        self.resume = resume
        # started_flag 记录 start 是否被调用。
        self.started_flag = False
        # stopped_flag 记录 stop 是否被调用。
        self.stopped_flag = False
        # questions 存储所有 ask 收到的问题文本。
        self.questions = []

    def start(self):
        """记录测试会话已启动。"""
        self.started_flag = True

    def stop(self):
        """记录测试会话已停止。"""
        self.stopped_flag = True

    def ask(self, message):
        """阻塞等待测试释放后返回可预测回答。"""
        self.questions.append(message)
        BlockingClaudeSession.started.set()
        if not BlockingClaudeSession.release.wait(timeout=2):
            raise TimeoutError("测试阻塞会话没有被释放")
        return f"回复:{message}"
