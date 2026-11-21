"""账号数据库迁移从后端环境配置读取连接串，不把凭据写入 ini。"""

from alembic import context
from sqlalchemy import create_engine, pool

from app.models.auth import AuthBase
from app.services.auth import AuthSettings


database_url = AuthSettings().database_url.get_secret_value()

if context.is_offline_mode():
    context.configure(url=database_url, target_metadata=AuthBase.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=AuthBase.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
