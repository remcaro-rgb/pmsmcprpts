// Saved reports (the agent's /api/reports): a question asked again on fresh data, from the
// sidebar or by email every day, week or month.

export type Schedule = "none" | "daily" | "weekly" | "monthly";

export type Report = {
  id: string;
  title: string;
  question: string;
  hotel: string | null;
  language: "en" | "es";
  schedule: Schedule;
  weekday: number; // for weekly: 0 = Monday
  created: number;
  last_run: string | null;
};

export type ReportList = { reports: Report[]; scheduling_available: boolean; send_time: string };
