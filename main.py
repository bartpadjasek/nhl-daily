"""Entry point for the NHL Daily digest.

Usage:
    python main.py                Start the daily scheduler (see scheduler.RUN_TIME, local time)
    python main.py --now          Run once: send if a recently completed game hasn't been sent,
                                  otherwise send the season recap if it's due, otherwise skip
    python main.py --force        Run the pipeline immediately, bypassing the game check
    python main.py --preview      Like --force, but write the email to preview/ instead of
                                  sending it (no Resend, no game log)
    python main.py --force-recap  Run the season recap pipeline immediately, bypassing the sentinel
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Parse arguments and either run the pipeline immediately or start the scheduler."""
    if "--force-recap" in sys.argv:
        logger.info("--force-recap flag detected: running season recap pipeline")
        from scheduler import run_recap_pipeline

        run_recap_pipeline()
    elif "--preview" in sys.argv:
        logger.info("--preview flag detected: building the email without sending it")
        from scheduler import run_pipeline

        run_pipeline(preview=True)
    elif "--force" in sys.argv:
        logger.info("--force flag detected: running pipeline, bypassing game check")
        from scheduler import run_pipeline

        run_pipeline(force=True)
    elif "--now" in sys.argv:
        logger.info("--now flag detected: running pipeline immediately")
        from scheduler import run_pipeline, run_recap_pipeline
        from season_recap import should_send_recap

        if run_pipeline():
            pass
        elif should_send_recap():
            run_recap_pipeline()
        else:
            logger.info("No unsent game and recap not due — skipping")
    else:
        from scheduler import start_scheduler

        start_scheduler()


if __name__ == "__main__":
    main()
