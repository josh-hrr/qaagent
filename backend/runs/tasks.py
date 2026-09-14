from django.tasks import task

from . import pipeline


@task()
def execute_run(run_id: int) -> None:
    """Background entry point. Picked up by `python manage.py db_worker`."""
    pipeline.execute(run_id)
