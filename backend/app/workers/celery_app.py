from celery import Celery

from app.config import settings

celery_app = Celery(
    "autopatch",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    beat_schedule={
        "expire-approval-gates": {
            "task": "expire_approval_gates",
            "schedule": 15.0,
        }
    },
)
