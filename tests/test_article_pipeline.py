import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import article_pipeline


def sample_item():
    return {
        "id": "202600001",
        "key": "id:202600001",
        "title": "테스트은행 제재관련 공시",
        "date": "2026.05.01",
        "url": "https://example.test/fss",
    }


class AutoWriterTaskTest(unittest.TestCase):
    def test_auto_writer_source_contains_fss_cartoon_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            config = article_pipeline.ServiceConfig(
                auto_writer_project_dir="/Users/sanghoon/codes/Auto-Writer",
                auto_writer_mode="dry-run",
                cms_review_status="미승인",
            )

            result = article_pipeline.write_auto_writer_source(
                job_dir,
                sample_item(),
                [job_dir / "pdf" / "sample.pdf"],
                "PDF 본문입니다.",
                config,
            )

            self.assertEqual(result["mode"], "dry-run")
            source_text = (job_dir / article_pipeline.AUTO_WRITER_SOURCE_FILE).read_text(encoding="utf-8")
            self.assertIn("금감원 징계해설 기사", source_text)
            self.assertIn("Herbert Block", source_text)
            self.assertIn("뉴요커 만평 스타일", source_text)
            self.assertIn("영어 사용 금지", source_text)
            self.assertIn("기사검토 상태: 미승인", source_text)

    def test_auto_writer_task_blocks_when_project_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            config = article_pipeline.ServiceConfig(
                auto_writer_project_dir=str(job_dir / "missing-auto-writer"),
                auto_writer_mode="live",
                cms_review_status="미승인",
            )

            result = article_pipeline.write_auto_writer_task(job_dir, sample_item(), config, [])

            self.assertFalse(result["ready"])
            self.assertTrue(any("Auto-Writer" in blocker for blocker in result["blockers"]))
            state = json.loads((job_dir / article_pipeline.AUTO_WRITER_STATE_FILE).read_text(encoding="utf-8"))
            self.assertEqual(state["stage"], "blocked")

    def test_process_item_creates_auto_writer_handoff_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auto_writer_dir = root / "Auto-Writer"
            auto_writer_dir.mkdir()
            config = article_pipeline.ServiceConfig(
                runs_dir=str(root / "runs"),
                auto_writer_project_dir=str(auto_writer_dir),
                auto_writer_mode="dry-run",
                cms_review_status="미승인",
            )
            item = sample_item()

            with (
                patch.object(article_pipeline, "download_job_pdfs", return_value=[root / "sample.pdf"]),
                patch.object(article_pipeline, "extract_all_pdf_text", return_value=("PDF 본문입니다.", [])),
            ):
                status = article_pipeline.process_item(item, config)

            job_dir = Path(status["job_dir"])
            self.assertEqual(status["status"], "auto_writer_ready")
            self.assertIn(article_pipeline.AUTO_WRITER_SOURCE_FILE, status["next_files"])
            self.assertIn(article_pipeline.AUTO_WRITER_TASK_FILE, status["next_files"])
            self.assertIn("auto_writer_task.md", status["next_files"])
            self.assertTrue((job_dir / article_pipeline.AUTO_WRITER_SOURCE_FILE).exists())
            self.assertTrue((job_dir / article_pipeline.AUTO_WRITER_STATE_FILE).exists())


if __name__ == "__main__":
    unittest.main()
