import sys
from loguru import logger as log

from controllers.launcher import create_controller


if __name__ == "__main__":

    controller_type = "system"
    controller_id = 0

    if len(sys.argv) == 2:
        controller_type = sys.argv[1].strip().lower()

    elif len(sys.argv) == 3:
        controller_type = sys.argv[1].strip().lower()
        controller_id = int(sys.argv[2])

    log.info(f"Starting controller: {controller_type} [{controller_id}]")

    while True:
        try:
            controller = create_controller(
                controller_type=controller_type,
                controller_id=controller_id
            )
            controller.run()

        except KeyboardInterrupt:
            log.info("Stopped by user")
            break

        except Exception as e:
            log.exception(e)
            break