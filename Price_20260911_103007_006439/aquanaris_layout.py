# -*- coding: utf-8 -*-
"""[호환 껍데기 · 2026-09-11] 아쿠나리스 배치 엔진은 aquanaris/layout.py 로 옮겼다.
옛 `import aquanaris_layout` · `from aquanaris_layout import *`(tools·옛 코드)를 그대로 살린다 —
이 이름으로 import 하면 aquanaris.layout 모듈 **그 자체**가 돌아온다(사본이 아니다)."""
import sys
from aquanaris import layout as _layout

sys.modules[__name__] = _layout
