"""单 Worker 轮询任务处理器。

运行方式: python -m api.worker
"""

import os
import signal
import time
from pathlib import Path

from api.db import (
    init_db,
    get_next_pending_job,
    mark_job_running,
    mark_job_completed,
    mark_job_failed,
)
from core.config import load_env
from core.logging import setup_logger
from schemas.job import JOB_STATUS_FAILED

logger = setup_logger(__name__)


def _get_db_path() -> Path:
    path_str = os.getenv("VIDEO_SKILL_DB_PATH", "./video_skill.db")
    return Path(path_str).resolve()


DB_PATH = _get_db_path()
POLL_INTERVAL = 2.0


class Worker:
    """轮询 SQLite 获取待处理任务并依次执行。"""

    def __init__(self, db_path: Path, poll_interval: float = POLL_INTERVAL) -> None:
        self.db_path = db_path
        self.poll_interval = poll_interval
        self._running = False

    def start(self) -> None:
        """启动 Worker 轮询循环。KeyboardInterrupt 时停止。"""
        self._running = True
        logger.info("Worker started, db=%s, poll_interval=%s", self.db_path, self.poll_interval)

        while self._running:
            try:
                job = get_next_pending_job(self.db_path)
                if job is None:
                    time.sleep(self.poll_interval)
                    continue

                logger.info("Picked job: id=%s video=%s", job.id, job.input_video_path)
                mark_job_running(self.db_path, job.id)

                try:
                    from scripts.run import run_pipeline
                    outputs = run_pipeline(
                        input_video_path=job.input_video_path,
                        output_dir=job.output_dir,
                        mode=job.mode,
                    )
                    mark_job_completed(self.db_path, job.id, **outputs.model_dump())
                    logger.info("Job completed: id=%s", job.id)
                except Exception as exc:
                    logger.exception("Job failed: id=%s", job.id)
                    mark_job_failed(self.db_path, job.id, str(exc))

            except KeyboardInterrupt:
                logger.info("Worker interrupted, stopping")
                self._running = False
                break
            except Exception:
                logger.exception("Worker loop error (non-job), continuing")
                time.sleep(self.poll_interval)

        logger.info("Worker stopped")

    def stop(self) -> None:
        """通知 Worker 停止。"""
        self._running = False


def main() -> None:
    """Worker 独立运行的入口点。"""
    load_env()
    init_db(DB_PATH)
    worker = Worker(db_path=DB_PATH)
    worker.start()


if __name__ == "__main__":
    main()