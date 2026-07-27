from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import Settings
from .errors import PipelineError
from .pipeline import PipelineOptions, execute
from .video import RenderOptions

LOG = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="viet-transform",
        description="Tao video review tieng Viet tu video ma ban co quyen su dung.",
    )
    parser.add_argument("source", help="Duong dan video hoac URL duoc yt-dlp ho tro")
    parser.add_argument("-o", "--output", type=Path, default=Path("output/final.mp4"))
    parser.add_argument("--work-dir", type=Path, default=Path("work/default"))
    parser.add_argument("--music", type=Path, help="Chon mot track thay vi lay ngau nhien")
    parser.add_argument("--seed", type=int, help="Seed de chon nhac co the lap lai")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--no-resume", action="store_true", help="Chay lai tat ca cac buoc")
    parser.add_argument("--no-flip", action="store_true", help="Khong lat ngang video")
    parser.add_argument("--zoom", type=float, default=1.06)
    parser.add_argument("--music-volume", type=float, default=0.12)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    try:
        settings = Settings.load(args.env_file)
        output = execute(
            PipelineOptions(
                source=args.source,
                output=args.output.resolve(),
                work_dir=args.work_dir.resolve(),
                music=args.music.resolve() if args.music else None,
                seed=args.seed,
                resume=not args.no_resume,
                render=RenderOptions(
                    zoom=args.zoom,
                    flip=not args.no_flip,
                    music_volume=args.music_volume,
                ),
            ),
            settings,
        )
        LOG.info("Hoan tat: %s", output)
        return 0
    except (PipelineError, ValueError) as exc:
        LOG.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOG.error("Da huy boi nguoi dung.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
