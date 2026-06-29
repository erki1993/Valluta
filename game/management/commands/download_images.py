import mimetypes
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from game.models import Question


class Command(BaseCommand):
    help = "Download images from image_url and store them locally in the image field."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be downloaded without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        qs = Question.objects.filter(image_url__gt="", image="")

        if not qs.exists():
            self.stdout.write("No questions with image_url and no local image found.")
            return

        self.stdout.write(f"Found {qs.count()} question(s) to process.")

        ok = 0
        failed = 0
        for question in qs:
            url = question.image_url
            self.stdout.write(f"  [{question.pk}] {url[:80]}")

            if dry_run:
                continue

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as response:
                    content_type = response.headers.get_content_type()
                    ext = mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".jpg"
                    # guess_extension can return .jpe for jpeg — normalise
                    if ext in (".jpe", ".jpeg"):
                        ext = ".jpg"
                    data = response.read()

                filename = f"question_{question.pk}{ext}"
                question.image.save(filename, ContentFile(data), save=False)
                question.image_url = ""
                question.save(update_fields=["image", "image_url"])
                self.stdout.write(self.style.SUCCESS(f"    -> saved as {filename}"))
                ok += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"    -> failed: {exc}"))
                failed += 1

        if not dry_run:
            self.stdout.write(f"\nDone. {ok} downloaded, {failed} failed.")
