"""Юнит-тесты решающих функций автопилота: пороги владельца, стоп-лист ядра, валидация текстов.
Запуск: python3 -m unittest discover infra/server/ads-watchdog/tests -v"""
import sys, pathlib, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import decisions as d  # noqa: E402


class DayHourStops(unittest.TestCase):
    def test_day_stop_owner_threshold_700(self):
        self.assertFalse(d.day_stop(700.0))   # ровно 700 — ещё нет
        self.assertTrue(d.day_stop(700.01))
        self.assertFalse(d.day_stop(0))

    def test_hour_stop_uses_point_about_hour_ago(self):
        now = 100_000.0
        pts = [{"ts": now - 3600, "cost": 100.0}]
        self.assertTrue(d.hour_stop(pts, now, 401.0))    # +301 за час
        self.assertFalse(d.hour_stop(pts, now, 399.0))   # +299 — нет

    def test_hour_stop_no_baseline(self):
        self.assertFalse(d.hour_stop([], 100_000.0, 10_000.0))
        # точка слишком свежая (10 мин) — базы нет, не паникуем
        pts = [{"ts": 100_000.0 - 600, "cost": 0.0}]
        self.assertFalse(d.hour_stop(pts, 100_000.0, 10_000.0))


class Autotargeting(unittest.TestCase):
    def test_at_share(self):
        self.assertTrue(d.at_share_alarm(40, 120))     # 33%
        self.assertFalse(d.at_share_alarm(20, 120))    # 17%
        self.assertFalse(d.at_share_alarm(90, 99))     # день < 100 ₽ — рано судить


class BidCeiling(unittest.TestCase):
    def test_steps_and_owner_cap_25(self):
        self.assertEqual(d.next_bid_ceiling(20.0), 25.0)
        self.assertIsNone(d.next_bid_ceiling(25.0))    # выше — только человек
        self.assertEqual(d.next_bid_ceiling(22.0), 25.0)  # не перепрыгиваем кэп


class MinusFilter(unittest.TestCase):
    def test_core_semantics_protected(self):
        got = d.filter_minus_candidates(
            ["ванной", "нейросеть аниме", "дизайн курсы", "торрент"], set())
        self.assertEqual(got, ["ванной", "торрент"])  # всё с корнями ядра — отсечено

    def test_dedup_existing_and_cap(self):
        existing = {"ванной"}
        cands = ["ванной", "санузел"] + [f"мусор{i}" for i in range(20)]
        got = d.filter_minus_candidates(cands, existing)
        self.assertNotIn("ванной", got)
        self.assertEqual(len(got), d.MINUS_MAX_PER_RUN)


class AdsRules(unittest.TestCase):
    def test_group_needs_new_ad(self):
        self.assertTrue(d.group_needs_new_ad(300, 5, 2, 8))     # CTR 1.7%
        self.assertFalse(d.group_needs_new_ad(299, 2, 2, 8))    # мало показов
        self.assertFalse(d.group_needs_new_ad(1000, 30, 2, 8))  # CTR 3%
        self.assertFalse(d.group_needs_new_ad(300, 5, 3, 8))    # уже 3 (лимит Директа)
        self.assertFalse(d.group_needs_new_ad(300, 5, 2, 3))    # добавляли недавно

    def test_valid_ad_texts(self):
        self.assertEqual(d.valid_ad_texts("Заголовок", "Второй", "Текст объявления."), [])
        probs = d.valid_ad_texts("х" * 57, "Второй", "Фото → дизайн")
        self.assertTrue(any("Title1" in p for p in probs))
        self.assertTrue(any("запрещённые символы" in p for p in probs))
        probs = d.valid_ad_texts("Лучше чем remplanner", "ок", "ок")
        self.assertTrue(any("чужой бренд" in p for p in probs))


if __name__ == "__main__":
    unittest.main()
