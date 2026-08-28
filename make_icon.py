# -*- coding: utf-8 -*-
"""生成安装器图标 installer.ico（蓝色圆角方块 + 白色终端箭头）"""
import os
from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 背景圆角矩形
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=56, fill=(37, 99, 235, 255))

# 白色 ">_" 终端符号：两段粗线组成 ">"
W = 24  # 线宽
chevron = [(66, 78), (122, 128), (66, 178)]
for i in range(len(chevron) - 1):
    d.line([chevron[i], chevron[i + 1]], fill="white", width=W)
    for p in (chevron[i], chevron[i + 1]):
        r = W // 2 - 2
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill="white")

# 下划线 "_"
d.rounded_rectangle([140, 162, 196, 162 + W - 8], radius=8, fill="white")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "installer.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                     (96, 96), (128, 128), (256, 256)])
print("icon saved:", out)
