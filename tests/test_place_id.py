import unittest
from unittest.mock import patch, MagicMock

from src.models import (
    Place,
    chij_to_hex,
    parse_place_id_from_url,
    normalize_place_id,
)
from src.itravels_sync import ITravelsClient


class TestPlaceIdNormalization(unittest.TestCase):
    def test_chij_to_hex_user_example(self):
        # Ví dụ thực tế người dùng yêu cầu:
        # "ChIJrYhLgoZncDER6fpXnhTtHH8" -> "0x31706786824b88ad:0x7f1ced149e57fae9"
        chij = "ChIJrYhLgoZncDER6fpXnhTtHH8"
        expected = "0x31706786824b88ad:0x7f1ced149e57fae9"
        self.assertEqual(chij_to_hex(chij), expected)

    def test_chij_to_hex_known_places(self):
        # Tháp Bà Ponagar
        self.assertEqual(
            chij_to_hex("ChIJUfK4YYxncDERfB2v8ZdvXxE"),
            "0x3170678c61b8f251:0x115f6f97f1af1d7c",
        )
        # Đảo Hòn Tằm
        self.assertEqual(
            chij_to_hex("ChIJ-b9_ywNhcDERqvfgsQl7cnM"),
            "0x31706103cb7fbff9:0x73727b09b1e0f7aa",
        )

    def test_chij_to_hex_invalid(self):
        self.assertIsNone(chij_to_hex(None))
        self.assertIsNone(chij_to_hex(""))
        self.assertIsNone(chij_to_hex("invalid"))
        self.assertIsNone(chij_to_hex("ChIJ_not_a_valid_protobuf"))
        self.assertIsNone(chij_to_hex("0x31706786824b88ad:0x7f1ced149e57fae9"))

    def test_parse_place_id_from_url_with_both_1s_and_19s(self):
        # URL có cả !1s (hex) và !19s (ChIJ) -> luôn ưu tiên lấy 0x...:0x...
        url = "https://www.google.com/maps/place/Th%C3%A1p+B%C3%A0+Ponagar/data=!4m7!3m6!1s0x3170678c61b8f251:0x115f6f97f1af1d7c!8m2!3d12.2653665!4d109.1953678!16s%2Fm%2F02x5pgr!19sChIJUfK4YYxncDERfB2v8ZdvXxE?authuser=0&hl=vi"
        self.assertEqual(
            parse_place_id_from_url(url),
            "0x3170678c61b8f251:0x115f6f97f1af1d7c",
        )

    def test_parse_place_id_from_url_with_only_1s(self):
        # URL chỉ có !1s (không có !19s)
        url = "https://www.google.com/maps/place/Bitexco+Financial+Tower/@10.7717064,106.7043759,17z/data=!3m1!4b1!4m6!3m5!1s0x31752f3acf87eaeb:0xc969a1975f3be32a!8m2!3d10.7717064!4d106.7043759"
        self.assertEqual(
            parse_place_id_from_url(url),
            "0x31752f3acf87eaeb:0xc969a1975f3be32a",
        )

    def test_parse_place_id_from_url_with_only_19s(self):
        # URL chỉ có !19s -> tự động decode sang 0x...:0x...
        url = "https://www.google.com/maps/place/SomePlace/data=!4m7!3m6!19sChIJrYhLgoZncDER6fpXnhTtHH8?hl=vi"
        self.assertEqual(
            parse_place_id_from_url(url),
            "0x31706786824b88ad:0x7f1ced149e57fae9",
        )

    def test_parse_place_id_from_url_encoded(self):
        # URL bị mã hoá URL percent-encoding
        url = "https%3A%2F%2Fwww.google.com%2Fmaps%2Fplace%2Fdata%3D%211s0x31706786824b88ad%3A0x7f1ced149e57fae9"
        self.assertEqual(
            parse_place_id_from_url(url),
            "0x31706786824b88ad:0x7f1ced149e57fae9",
        )

    def test_normalize_place_id(self):
        # Dạng hex có chữ hoa -> về chữ thường
        self.assertEqual(
            normalize_place_id("0x31706786824B88AD:0x7F1CED149E57FAE9"),
            "0x31706786824b88ad:0x7f1ced149e57fae9",
        )
        # Dạng ChIJ -> decode sang 0x...:0x...
        self.assertEqual(
            normalize_place_id("ChIJrYhLgoZncDER6fpXnhTtHH8"),
            "0x31706786824b88ad:0x7f1ced149e57fae9",
        )
        # Không có place_id nhưng có url
        url = "https://www.google.com/maps/place/data=!1s0x31706786824b88ad:0x7f1ced149e57fae9"
        self.assertEqual(
            normalize_place_id(None, url=url),
            "0x31706786824b88ad:0x7f1ced149e57fae9",
        )

    def test_place_dataclass_auto_normalizes(self):
        # Place với ChIJ place_id -> tự động chuẩn hoá trong __post_init__ và to_dict()
        p = Place(
            title="Nhà hàng mẫu",
            place_id="ChIJrYhLgoZncDER6fpXnhTtHH8",
        )
        self.assertEqual(p.place_id, "0x31706786824b88ad:0x7f1ced149e57fae9")
        d = p.to_dict()
        self.assertEqual(d["place_id"], "0x31706786824b88ad:0x7f1ced149e57fae9")

        # Place với url -> tự động gán place_id dạng 0x...:0x...
        p2 = Place(
            title="Bitexco",
            url="https://www.google.com/maps/place/Bitexco/data=!1s0x31752f3acf87eaeb:0xc969a1975f3be32a",
        )
        self.assertEqual(p2.place_id, "0x31752f3acf87eaeb:0xc969a1975f3be32a")

    @patch("requests.post")
    def test_itravels_sync_always_sends_hex_place_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_post.return_value = mock_resp

        client = ITravelsClient(api_key="test-key", base_url="https://api.itravels.vn")

        # Gửi dữ liệu chứa place_id dạng ChIJ
        items = [
            {
                "title": "Nhà hàng A",
                "place_id": "ChIJrYhLgoZncDER6fpXnhTtHH8",
                "url": "https://www.google.com/maps/place/A",
            },
            {
                "title": "Nhà hàng B",
                "place_id": None,
                "url": "https://www.google.com/maps/place/B/data=!1s0x3170678c61b8f251:0x115f6f97f1af1d7c",
            },
        ]

        success, code, msg, resp = client.send_batch("am-thuc", items)
        self.assertTrue(success)

        # Kiểm tra payload json gửi lên requests.post
        call_kwargs = mock_post.call_args[1]
        sent_items = call_kwargs["json"]

        self.assertEqual(sent_items[0]["place_id"], "0x31706786824b88ad:0x7f1ced149e57fae9")
        self.assertEqual(sent_items[1]["place_id"], "0x3170678c61b8f251:0x115f6f97f1af1d7c")


if __name__ == "__main__":
    unittest.main()
