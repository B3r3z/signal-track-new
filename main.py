import argparse
from loguru import logger as log

from controllers.launcher import create_controller


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="SignalTrack controller")
    parser.add_argument(
        "controller_type",
        nargs="?",
        default="system",
        choices=["system", "tx", "rx", "fsv"],
    )
    parser.add_argument("controller_id", nargs="?", default=0, type=int)
    parser.add_argument("--config", default=None)

    args = parser.parse_args()

    controller_type = args.controller_type.strip().lower()
    controller_id = int(args.controller_id)

    log.info(f"Starting controller: {controller_type} [{controller_id}]")

    while True:
        try:
            controller = create_controller(
                controller_type=controller_type,
                controller_id=controller_id,
                config_path=args.config,
            )
            controller.run()

        except KeyboardInterrupt:
            log.info("Stopped by user")
            break

        except Exception as e:
            log.exception(e)
            break
