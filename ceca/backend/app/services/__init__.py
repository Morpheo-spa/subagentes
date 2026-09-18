"""Business logic.

Nothing in here imports FastAPI or touches a Request. Services receive domain
types and a :class:`app.deps.TenantContext`, and every read of a tenant scoped
table goes through ``scoped_select``.
"""
