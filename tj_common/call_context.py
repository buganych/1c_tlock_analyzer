"""Resolve CALL event context label (Python + ClickHouse SQL)."""

from __future__ import annotations

from tj_common.models_call import CallEvent

CONTEXT_SQL_EXPR = """
if(length(context) > 0, context,
  if(length(module) > 0 AND length(method) > 0, concat(module, '.', method),
    if(length(func) > 0, func,
      if(length(mname) > 0 OR length(iname) > 0,
        concat(if(length(mname) > 0, mname, ''),
               if(length(iname) > 0, concat('.', iname), '')),
        '(unknown)'))))
""".strip()


def resolve_call_context(
    *,
    context: str = "",
    module: str = "",
    method: str = "",
    func: str = "",
    mname: str = "",
    iname: str = "",
) -> str:
    if context:
        return context
    if module and method:
        return f"{module}.{method}"
    if func:
        return func
    if mname or iname:
        if mname and iname:
            return f"{mname}.{iname}"
        return mname or iname
    return "(unknown)"


def resolve_call_event_context(event: CallEvent) -> str:
    return resolve_call_context(
        context=event.context_raw,
        module=event.module,
        method=event.method,
        func=event.func,
        mname=event.mname,
        iname=event.iname,
    )
