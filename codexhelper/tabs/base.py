# -*- coding: utf-8 -*-
"""分页基类：约定 Tab 持有 app 引用，通过 app 注册消息路由与操作按钮。"""


class Tab:
    def __init__(self, app, parent):
        self.app = app
        self.parent = parent
        self.build()

    # 便捷转发
    def q(self, *msg):
        self.app.q.put(msg)

    def log(self, text, tag="normal"):
        self.app._append_log(text, tag)

    def register(self, kind, handler):
        self.app.route[kind] = handler

    def build(self):
        raise NotImplementedError
