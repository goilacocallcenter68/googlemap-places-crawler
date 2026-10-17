import os
import shutil
import tempfile
import unittest

from src.keyword_loader import load_keywords_from_file, resolve_job_keywords


class TestKeywordLoader(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_place_example_csv(self):
        csv_path = os.path.abspath("place.example.csv")
        self.assertTrue(os.path.exists(csv_path), "place.example.csv must exist in repo root")

        keywords = load_keywords_from_file(csv_path)
        self.assertEqual(len(keywords), 78)
        self.assertEqual(keywords[0], "Bãi biển Trần Phú")
        self.assertEqual(keywords[1], "Hòn Chồng")
        self.assertEqual(keywords[-1], "Suối nước nóng Tân Sơn")

    def test_load_csv_with_header_and_quotes(self):
        fpath = os.path.join(self.test_dir, "test.csv")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write('id,name,address\n')
            f.write('1,"Tháp Bà, Nha Trang",Khánh Hòa\n')
            f.write('2,"Hòn Mun",Nha Trang\n')
            f.write('3,"Hòn Mun",Duplicate\n')

        keywords = load_keywords_from_file(fpath)
        self.assertEqual(keywords, ["Tháp Bà, Nha Trang", "Hòn Mun"])

    def test_load_txt_with_comments_and_blanks(self):
        fpath = os.path.join(self.test_dir, "test.txt")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("# Danh sách từ khóa\n")
            f.write("\n")
            f.write("Khách sạn Nha Trang\n")
            f.write("  Homestay Cam Ranh  \n")
            f.write("# comment khác\n")
            f.write("Khách sạn Nha Trang\n")

        keywords = load_keywords_from_file(fpath)
        self.assertEqual(keywords, ["Khách sạn Nha Trang", "Homestay Cam Ranh"])

    def test_load_json_formats(self):
        fpath_array = os.path.join(self.test_dir, "test_array.json")
        with open(fpath_array, "w", encoding="utf-8") as f:
            f.write('["Phở Hà Nội", "Bún chả", "Phở Hà Nội"]')

        kws1 = load_keywords_from_file(fpath_array)
        self.assertEqual(kws1, ["Phở Hà Nội", "Bún chả"])

        fpath_obj = os.path.join(self.test_dir, "test_obj.json")
        with open(fpath_obj, "w", encoding="utf-8") as f:
            f.write('[{"keyword": "Bánh mì"}, {"name": "Cơm tấm"}]')

        kws2 = load_keywords_from_file(fpath_obj)
        self.assertEqual(kws2, ["Bánh mì", "Cơm tấm"])

    def test_keyword_template(self):
        fpath = os.path.join(self.test_dir, "places.txt")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("Vinpearl\nHòn Chồng\n")

        keywords = load_keywords_from_file(fpath, template="{keyword} Nha Trang")
        self.assertEqual(keywords, ["Vinpearl Nha Trang", "Hòn Chồng Nha Trang"])

    def test_resolve_job_keywords_combination(self):
        fpath = os.path.join(self.test_dir, "custom.csv")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("Từ khóa từ file 1\nTừ khóa từ file 2\n")

        job_data = {
            "keywords_file": "custom.csv",
            "keywords": ["Từ khóa inline", "Từ khóa từ file 1"],  # Có 1 trùng lặp
        }

        kws, watched, errors = resolve_job_keywords(job_data, base_dir=self.test_dir)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(watched), 1)
        self.assertEqual(kws, ["Từ khóa từ file 1", "Từ khóa từ file 2", "Từ khóa inline"])

    def test_resolve_job_keywords_missing_file(self):
        job_data = {
            "keywords_file": "non_existent_file.csv"
        }
        kws, watched, errors = resolve_job_keywords(job_data, base_dir=self.test_dir)
        self.assertEqual(len(kws), 0)
        self.assertEqual(len(errors), 1)
    def test_job_config_with_keywords_file(self):
        from src.scheduler import JobConfig
        data = {
            "keywords_file": "place.example.csv",
            "limit": 1,
            "schedule": {"cron": "0 4 * * 0"},
        }
        cfg = JobConfig("dia_danh", data, config_dir=os.getcwd())
        errors = cfg.validate()
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(cfg.keywords), 78)
        self.assertEqual(cfg.limit, 1)

    def test_save_consolidated_job_results(self):
        import json
        from src.models import Place
        from src.scheduler import save_consolidated_job_results

        p1 = Place(title="Hòn Chồng", place_id="ChIJ_001")
        p2 = Place(title="Tháp Bà", place_id="ChIJ_002")
        p3 = Place(title="Hòn Chồng Duplicate", place_id="ChIJ_001")  # Trùng place_id

        out_path = save_consolidated_job_results([p1, p2, p3], "test_job", self.test_dir)
        self.assertTrue(os.path.exists(out_path))

        with open(out_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        self.assertEqual(len(saved_data), 2)
        self.assertEqual(saved_data[0]["title"], "Hòn Chồng")
        self.assertEqual(saved_data[1]["title"], "Tháp Bà")


if __name__ == "__main__":
    unittest.main()
