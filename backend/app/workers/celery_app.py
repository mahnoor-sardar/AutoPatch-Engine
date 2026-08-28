from celery import Celery

from app.config import settings

celery_app = Celery(
    "autopatch",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_default_queue="celery",
    task_default_exchange="celery",
    task_default_routing_key="celery",
    task_create_missing_queues=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "expire-approval-gates": {
            "task": "expire_approval_gates",
            "schedule": 15.0,
        }
    },
)
