from celery import Celery
from celery.schedules import crontab
from kombu import Queue
from app.config import settings

celery_app = Celery(
    "omr_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.CELERY_ALWAYS_EAGER,
    task_eager_propagates=settings.CELERY_ALWAYS_EAGER,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_soft_time_limit=600,
    task_time_limit=660,
    task_default_queue="celery",
    task_queues=(
        Queue("omr_compute", routing_key="omr.#"),
        Queue("io_tasks", routing_key="io.#"),
        Queue("celery", routing_key="celery"),
    ),
    task_routes={
        "process_score": {"queue": "omr_compute"},
        "prune_storage": {"queue": "io_tasks"},
    },
    beat_schedule={
        "daily-storage-prune": {
            "task": "prune_storage",
            "schedule": crontab(hour=3, minute=0),  # Daily at 03:00 UTC
        },
    },
)
