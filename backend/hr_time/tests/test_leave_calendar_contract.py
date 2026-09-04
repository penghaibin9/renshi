from datetime import date, timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_time.services.leave_request_service import LeaveRequestService
from hr_time.services.calendar_service import CalendarService, CalendarServiceError


class LeaveCalendarContractTests(SimpleTestCase):
    def _request(self, start, end, start_breakdown="FULL_DAY", end_breakdown="FULL_DAY"):
        return SimpleNamespace(
            start_at=start,
            end_at=end,
            start_breakdown=start_breakdown,
            end_breakdown=end_breakdown,
        )

    def test_same_day_half_day_uses_half_unit(self):
        day = date(2026, 9, 2)
        request = self._request(day, day, "HALF_DAY_AM", "HALF_DAY_AM")
        self.assertEqual(
            LeaveRequestService._day_fraction(request, [day]),
            0.5,
        )

    def test_cross_day_pm_to_am_deducts_both_boundaries(self):
        start = date(2026, 9, 2)
        end = date(2026, 9, 4)
        request = self._request(start, end, "HALF_DAY_PM", "HALF_DAY_AM")
        self.assertEqual(
            LeaveRequestService._day_fraction(
                request, [start, date(2026, 9, 3), end]
            ),
            2,
        )

    def test_leave_request_model_has_frozen_calculation_snapshot(self):
        from hr_time.models import HrLeaveRequest

        field = HrLeaveRequest._meta.get_field("calculation_snapshot")
        self.assertEqual(field.get_default(), {})

    def test_workbench_submit_uses_authoritative_calendar_by_default(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "api" / "workbench.py"
        ).read_text(encoding="utf-8")
        self.assertIn("LeaveRequestService.submit(item)", source)
        self.assertNotIn("LeaveRequestService.submit(item, calendar_days=", source)

    def test_annual_calendar_requires_every_date_and_explicit_minutes(self):
        rows = []
        current = date(2026, 1, 1)
        while current.year == 2026:
            working = current.weekday() < 5
            rows.append(
                {
                    "date": current.isoformat(),
                    "dayType": "REGULAR_WORKDAY" if working else "REST_DAY",
                    "isWorkingDay": working,
                    "expectedWorkMinutes": 480 if working else 0,
                }
            )
            current += timedelta(days=1)
        validated = CalendarService._validated_annual_days(year=2026, rows=rows)
        self.assertEqual(len(validated), 365)

        with self.assertRaises(CalendarServiceError) as caught:
            CalendarService._validated_annual_days(year=2026, rows=rows[:-1])
        self.assertEqual(caught.exception.code, "CALENDAR_IMPORT_INCOMPLETE")

    def test_schedule_workspace_exposes_calendar_import_not_weekday_authority(self):
        from pathlib import Path

        backend_root = Path(__file__).resolve().parents[2]
        template = (
            backend_root / "hr_time" / "templates" / "hr_time" / "workspace.html"
        ).read_text(encoding="utf-8")
        script = (
            backend_root.parent / "frontend" / "static" / "hr" / "js" / "pages" / "hr11-actions.js"
        ).read_text(encoding="utf-8")
        self.assertIn("data-open-calendar-import", template)
        self.assertIn("/api/v1/hr/time/calendars/import", script)
        self.assertIn("国务院放假通知和学校校历", script)
