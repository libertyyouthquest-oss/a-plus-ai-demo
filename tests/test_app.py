import os
import tempfile
import unittest

os.environ["DATABASE_PATH"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.pop("ARK_API_KEY", None)

from app import app, get_db, init_db


class AppTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        self.assertEqual(response.get_json()["database"], "ok")

    def test_empty_input_is_friendly(self):
        response = self.client.post("/api/analyze", json={"idea": ""})
        self.assertEqual(response.status_code, 400)
        self.assertIn("请先输入", response.get_json()["error"])

    def test_missing_key_is_not_fake_success(self):
        response = self.client.post("/api/analyze", json={"idea": "面向社团的活动策划助手"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("暂未调用模型", response.get_json()["error"])

    def test_database_read_write(self):
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO analyses (idea, result, model) VALUES (?, ?, ?)",
                ("数据库测试输入", "数据库测试结果", "test-only"),
            )
            db.commit()
        response = self.client.get("/api/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["idea"], "数据库测试输入")


if __name__ == "__main__":
    unittest.main()
