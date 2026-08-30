export type Health = {
  ok: boolean;
  postgres: boolean;
  redis: boolean;
};

export type Run = {
  id: number;
  repo: string;
  ref?: string | null;
  status: string;
  pipeline_stage?: string | null;
  control_state?: string | null;
  current_diff?: string | null;
  error?: string | null;
  patch_attempts?: number | null;
  pr_url?: string | null;
  duration_ms?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  symbol_count?: number | null;
  e2b_sandbox_id?: string | null;
  stack_trace?: string | null;
};

export type RunListResponse = {
  stats?: {
    total: number;
    successful: number;
    running: number;
    failed: number;
  };
  runs: Run[];
};

export type AuditEvent = {
  id: number;
  run_id?: number | null;
  repository?: string | null;
  action: string;
  device_id?: string | null;
  detail?: string | null;
  actor?: string | null;
  result?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
};

export type ConnectedRepository = {
  full_name: string;
  default_branch: string;
  installation_id: number;
};

export type WsPayload = {
  runs?: Run[];
  event?: {
    type?: string;
    title?: string;
    body?: string;
    run_id?: number;
    status?: string;
    current_diff?: string | null;
    pr_url?: string | null;
  };
};

export type Diagnosis = {
  run_id: number;
  diagnosis: string | null;
  created_at: string | null;
};

export type ParsedStack = {
  exceptionType: string | null;
  message: string | null;
  file: string | null;
  line: number | null;
  functionName: string | null;
};
