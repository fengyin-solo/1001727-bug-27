"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import boiler as router_boiler
from app.routers import vessel as router_vessel
from app.routers import pressurepipe as router_pressurepipe
from app.routers import crane as router_crane
from app.routers import elevator as router_elevator
from app.routers import forklift as router_forklift
from app.routers import plan as router_plan
from app.routers import spotcheck as router_spotcheck
from app.routers import lubricate as router_lubricate
from app.routers import inspect as router_inspect
from app.routers import report as router_report
from app.routers import hazard as router_hazard
from app.routers import rectify as router_rectify
from app.routers import register as router_register
from app.routers import operator as router_operator
from app.routers import spare as router_spare
from app.routers import contract as router_contract
from app.routers import settle as router_settle
from app.routers import dispatch as router_dispatch

ROUTERS = [router_boiler, router_vessel, router_pressurepipe, router_crane, router_elevator, router_forklift, router_plan, router_spotcheck, router_lubricate, router_inspect, router_report, router_hazard, router_rectify, router_register, router_operator, router_spare, router_contract, router_settle, router_dispatch]
