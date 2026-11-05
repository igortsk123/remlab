import type { QuizRow } from "@/modules/partner-report/quiz";
import type { DirectRow, FunnelRow } from "@/modules/partner-report/report";

export type ReportData = {
  partner: { id: string; name: string };
  timezone: string;
  weeks: FunnelRow[];
  byApartment: FunnelRow[];
  total: FunnelRow;
  direct: DirectRow[];
  /** Блок «Знакомство» (onb-12): нет событий опроса — нет и поля. */
  quiz?: QuizRow[];
  apartments: Record<string, string>;
  generatedAt: string;
};
