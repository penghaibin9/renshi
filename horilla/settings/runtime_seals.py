"""Runtime wiring for the retired Horilla formal-write seal.

Keep this wiring centralized so every settings entrypoint installs the same
request context cleanup, final ORM write router, and stable 410 translator.
"""

THREAD_LOCAL_MIDDLEWARE = "horilla.horilla_middlewares.ThreadLocalMiddleware"
COMPANY_MIDDLEWARE = "base.middleware.CompanyMiddleware"
SAFE_COMPANY_MIDDLEWARE = "platform_access.middleware.SafeCompanyMiddleware"
LEGACY_WRITE_MIDDLEWARE = "horilla.legacy_hr_cutover.LegacyWriteAuthorityMiddleware"
LEGACY_WRITE_ROUTER = "horilla.legacy_hr_cutover.LegacyWriteAuthorityRouter"


def install_legacy_runtime_seals(namespace):
    """Install the final legacy-write guards into one Django settings namespace."""
    middleware = list(namespace.get("MIDDLEWARE", []))

    company_middleware = (
        SAFE_COMPANY_MIDDLEWARE
        if SAFE_COMPANY_MIDDLEWARE in middleware
        else COMPANY_MIDDLEWARE
    )

    if THREAD_LOCAL_MIDDLEWARE not in middleware:
        if company_middleware in middleware:
            company_index = middleware.index(company_middleware)
        else:
            company_index = len(middleware)
        middleware.insert(company_index, THREAD_LOCAL_MIDDLEWARE)

    if LEGACY_WRITE_MIDDLEWARE not in middleware:
        if company_middleware in middleware:
            company_index = middleware.index(company_middleware)
            middleware.insert(company_index + 1, LEGACY_WRITE_MIDDLEWARE)
        else:
            middleware.append(LEGACY_WRITE_MIDDLEWARE)

    routers = list(namespace.get("DATABASE_ROUTERS", []))
    if LEGACY_WRITE_ROUTER not in routers:
        routers.insert(0, LEGACY_WRITE_ROUTER)

    namespace["MIDDLEWARE"] = middleware
    namespace["DATABASE_ROUTERS"] = routers
