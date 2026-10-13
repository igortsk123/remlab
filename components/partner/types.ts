import type { DirectRow, FunnelRow } from "@/modules/partner-report/report";

export type ReportData = {
  partner: { id: string; name: string };
  timezone: string;
  weeks: FunnelRow[];
  byApartment: FunnelRow[];
  total: FunnelRow;
  direct: DirectRow[];
  apartments: Record<string, string>;
  generatedAt: string;
};
