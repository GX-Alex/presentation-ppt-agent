export interface DiagramValidationIssue {
  level: "critical" | "warning";
  code: string;
  message: string;
  cell_id?: string | null;
  suggestion?: string;
}

export interface DiagramValidationPayload {
  valid: boolean;
  fixed?: boolean;
  fixes?: string[];
  warnings?: string[];
  error?: string | null;
  review_passed?: boolean;
  review_mode?: "structural" | "heuristic" | "hybrid" | "vlm";
  issues?: DiagramValidationIssue[];
  suggestions?: string[];
  retry_recommended?: boolean;
  retry_count?: number;
  max_retries?: number;
  score?: number;
  critical_count?: number;
  warning_count?: number;
  snapshot_source?: string;
  updated_at?: string;
}

export interface DiagramSessionPayload {
  session_id: string;
  task_id: string;
  version: number;
  xml: string;
  summary: string;
  source: string;
  created_at: string;
  svg?: string | null;
  png?: string | null;
  validation?: DiagramValidationPayload | null;
}