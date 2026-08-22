"""baseline：冻结当前运行时惰性 DDL 的全量 schema（2026-08-22）。

来源：pg_dump --schema-only（postgres 16.14），对一次性库触发全部运行时惰性建表
（conversation / auth / memory / jobs / attachments 五个 store 的 _ensure 路径）
后导出。此后新增字段一律新增 migration；各 store 的 `_ensure` 仅作开发兜底，
生产环境以本目录迁移为准（对比测试：tests/integration/test_alembic_baseline.py）。

Revision ID: 0001_baseline
"""
from __future__ import annotations

from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels = None
depends_on = None

SCHEMA_SQL = r"""
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.14 (Debian 16.14-1.pgdg13+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: admin_audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_audit_events (
    id bigint NOT NULL,
    actor_id text NOT NULL,
    action text NOT NULL,
    target_user_id text,
    context jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: admin_audit_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.admin_audit_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: admin_audit_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.admin_audit_events_id_seq OWNED BY public.admin_audit_events.id;


--
-- Name: agent_run_retrievals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_run_retrievals (
    id uuid NOT NULL,
    run_id uuid NOT NULL,
    query_index integer NOT NULL,
    query_text_redacted text,
    scope character varying(50),
    document_id character varying(255),
    chunk_id character varying(255),
    recall_score double precision,
    rerank_score double precision,
    rank_before integer,
    rank_after integer,
    used_in_final_context boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    retrieval_source character varying(30) DEFAULT 'auto'::character varying NOT NULL
);


--
-- Name: agent_run_tool_calls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_run_tool_calls (
    id uuid NOT NULL,
    run_id uuid NOT NULL,
    tool_name character varying(150) NOT NULL,
    input_redacted jsonb,
    output_summary text,
    status character varying(30) NOT NULL,
    duration_ms integer,
    requires_hitl boolean DEFAULT false NOT NULL,
    hitl_status character varying(30),
    error_type character varying(100),
    error_summary text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runs (
    id uuid NOT NULL,
    user_id character varying(64) NOT NULL,
    thread_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    message_id uuid NOT NULL,
    module character varying(50) NOT NULL,
    agent_id character varying(100) NOT NULL,
    model character varying(150) NOT NULL,
    prompt_version character varying(80) NOT NULL,
    agent_version character varying(80) NOT NULL,
    status character varying(30) NOT NULL,
    input_tokens integer,
    output_tokens integer,
    total_tokens integer,
    latency_ms integer,
    langsmith_run_id character varying(255),
    error_type character varying(100),
    error_code character varying(100),
    error_summary text,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    effective_tools jsonb
);


--
-- Name: auth_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_accounts (
    id text NOT NULL,
    username text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    token_version integer DEFAULT 0 NOT NULL,
    must_change_password boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    avatar text,
    display_name text,
    CONSTRAINT auth_accounts_role_check CHECK ((role = ANY (ARRAY['admin'::text, 'user'::text, 'quality_reviewer'::text]))),
    CONSTRAINT auth_accounts_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text])))
);


--
-- Name: auth_login_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_login_attempts (
    key text NOT NULL,
    failures integer DEFAULT 0 NOT NULL,
    window_start timestamp with time zone,
    locked_until timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: auth_refresh_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_refresh_sessions (
    token_hash text NOT NULL,
    user_id text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone
);


--
-- Name: chat_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_attachments (
    id uuid NOT NULL,
    user_id character varying(64) NOT NULL,
    thread_id character varying(64) NOT NULL,
    original_filename character varying(500) NOT NULL,
    storage_key character varying(1000) NOT NULL,
    mime_type character varying(150),
    size_bytes bigint,
    status character varying(30) NOT NULL,
    parser_type character varying(100),
    parser_error text,
    knowledge_document_id uuid,
    created_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone
);


--
-- Name: conversation_turns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_turns (
    id uuid NOT NULL,
    thread_id uuid NOT NULL,
    user_id character varying(64) NOT NULL,
    sequence_no integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversations (
    id uuid NOT NULL,
    user_id character varying(64) NOT NULL,
    module character varying(50) NOT NULL,
    title character varying(255),
    retrieval_scope jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    last_active_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    legacy_thread_id character varying(255)
);


--
-- Name: episodic_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.episodic_events (
    id text NOT NULL,
    user_id text NOT NULL,
    thread_id text NOT NULL,
    parent_id text,
    type text NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    ts text NOT NULL
);


--
-- Name: eval_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.eval_cases (
    id uuid NOT NULL,
    source_feedback_id uuid NOT NULL,
    status character varying(30) NOT NULL,
    target_agent character varying(100) NOT NULL,
    input_text text NOT NULL,
    context_json jsonb,
    expected_behavior text,
    rubric jsonb NOT NULL,
    failure_reason character varying(100),
    source_model character varying(150),
    source_prompt_version character varying(80),
    source_agent_version character varying(80),
    created_by character varying(64) NOT NULL,
    approved_by character varying(64),
    created_at timestamp with time zone NOT NULL,
    approved_at timestamp with time zone
);


--
-- Name: feedback_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_audit_log (
    id uuid NOT NULL,
    actor_user_id character varying(64) NOT NULL,
    action character varying(80) NOT NULL,
    resource_type character varying(80) NOT NULL,
    resource_id character varying(128) NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: feedback_review_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_review_events (
    id uuid NOT NULL,
    feedback_id uuid NOT NULL,
    reviewer_user_id character varying(64) NOT NULL,
    event_type character varying(50) NOT NULL,
    old_value jsonb,
    new_value jsonb,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: feedback_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_reviews (
    id uuid NOT NULL,
    feedback_id uuid NOT NULL,
    reviewer_user_id character varying(64) NOT NULL,
    root_cause character varying(50),
    status character varying(50) NOT NULL,
    reviewer_note text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: feedback_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.feedback_snapshots (
    id uuid NOT NULL,
    feedback_id uuid NOT NULL,
    user_id character varying(64) NOT NULL,
    snapshot_json jsonb NOT NULL,
    redaction_version character varying(80) NOT NULL,
    redaction_count integer NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jobs (
    fingerprint text NOT NULL,
    url text DEFAULT ''::text NOT NULL,
    title text NOT NULL,
    company text DEFAULT ''::text NOT NULL,
    city text DEFAULT ''::text NOT NULL,
    salary text DEFAULT ''::text NOT NULL,
    experience text DEFAULT ''::text NOT NULL,
    jd text DEFAULT ''::text NOT NULL,
    keywords text[] DEFAULT '{}'::text[] NOT NULL,
    source text DEFAULT 'mcp-jobs'::text NOT NULL,
    crawled_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: memory_global_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memory_global_policy (
    id integer NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    generate boolean DEFAULT true NOT NULL,
    use boolean DEFAULT true NOT NULL,
    updated_at text NOT NULL,
    CONSTRAINT memory_global_policy_id_check CHECK ((id = 1))
);


--
-- Name: message_feedback; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.message_feedback (
    id uuid NOT NULL,
    user_id character varying(64) NOT NULL,
    thread_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    message_id uuid NOT NULL,
    run_id uuid NOT NULL,
    rating character varying(16) NOT NULL,
    reason character varying(50),
    comment text,
    share_context boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.messages (
    id uuid NOT NULL,
    thread_id uuid NOT NULL,
    turn_id uuid NOT NULL,
    user_id character varying(64) NOT NULL,
    role character varying(20) NOT NULL,
    content text NOT NULL,
    run_id uuid,
    regenerated_from_message_id uuid,
    status character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    deleted_at timestamp with time zone,
    metadata jsonb
);


--
-- Name: regeneration_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regeneration_keys (
    user_id character varying(64) NOT NULL,
    key character varying(200) NOT NULL,
    message_id uuid,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: semantic_facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.semantic_facts (
    user_id text NOT NULL,
    name text NOT NULL,
    type text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    source text DEFAULT ''::text NOT NULL,
    confidence real DEFAULT 1.0 NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_at text NOT NULL,
    modified_at text NOT NULL
);


--
-- Name: threads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.threads (
    user_id text NOT NULL,
    thread_id text NOT NULL,
    title text DEFAULT ''::text NOT NULL,
    module text DEFAULT 'chat'::text NOT NULL,
    pinned boolean DEFAULT false NOT NULL,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    retrieval_scope jsonb
);


--
-- Name: user_memory_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_memory_policy (
    user_id text NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    generate boolean DEFAULT true NOT NULL,
    use boolean DEFAULT true NOT NULL,
    updated_at text NOT NULL
);


--
-- Name: admin_audit_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_audit_events ALTER COLUMN id SET DEFAULT nextval('public.admin_audit_events_id_seq'::regclass);


--
-- Name: admin_audit_events admin_audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_audit_events
    ADD CONSTRAINT admin_audit_events_pkey PRIMARY KEY (id);


--
-- Name: agent_run_retrievals agent_run_retrievals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_retrievals
    ADD CONSTRAINT agent_run_retrievals_pkey PRIMARY KEY (id);


--
-- Name: agent_run_tool_calls agent_run_tool_calls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_run_tool_calls
    ADD CONSTRAINT agent_run_tool_calls_pkey PRIMARY KEY (id);


--
-- Name: agent_runs agent_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (id);


--
-- Name: auth_accounts auth_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_accounts
    ADD CONSTRAINT auth_accounts_pkey PRIMARY KEY (id);


--
-- Name: auth_accounts auth_accounts_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_accounts
    ADD CONSTRAINT auth_accounts_username_key UNIQUE (username);


--
-- Name: auth_login_attempts auth_login_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_login_attempts
    ADD CONSTRAINT auth_login_attempts_pkey PRIMARY KEY (key);


--
-- Name: auth_refresh_sessions auth_refresh_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_refresh_sessions
    ADD CONSTRAINT auth_refresh_sessions_pkey PRIMARY KEY (token_hash);


--
-- Name: chat_attachments chat_attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_attachments
    ADD CONSTRAINT chat_attachments_pkey PRIMARY KEY (id);


--
-- Name: conversation_turns conversation_turns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns
    ADD CONSTRAINT conversation_turns_pkey PRIMARY KEY (id);


--
-- Name: conversation_turns conversation_turns_thread_id_sequence_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns
    ADD CONSTRAINT conversation_turns_thread_id_sequence_no_key UNIQUE (thread_id, sequence_no);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: episodic_events episodic_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.episodic_events
    ADD CONSTRAINT episodic_events_pkey PRIMARY KEY (user_id, id);


--
-- Name: eval_cases eval_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.eval_cases
    ADD CONSTRAINT eval_cases_pkey PRIMARY KEY (id);


--
-- Name: feedback_audit_log feedback_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_audit_log
    ADD CONSTRAINT feedback_audit_log_pkey PRIMARY KEY (id);


--
-- Name: feedback_review_events feedback_review_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_review_events
    ADD CONSTRAINT feedback_review_events_pkey PRIMARY KEY (id);


--
-- Name: feedback_reviews feedback_reviews_feedback_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_reviews
    ADD CONSTRAINT feedback_reviews_feedback_id_key UNIQUE (feedback_id);


--
-- Name: feedback_reviews feedback_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_reviews
    ADD CONSTRAINT feedback_reviews_pkey PRIMARY KEY (id);


--
-- Name: feedback_snapshots feedback_snapshots_feedback_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_snapshots
    ADD CONSTRAINT feedback_snapshots_feedback_id_key UNIQUE (feedback_id);


--
-- Name: feedback_snapshots feedback_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_snapshots
    ADD CONSTRAINT feedback_snapshots_pkey PRIMARY KEY (id);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (fingerprint);


--
-- Name: memory_global_policy memory_global_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memory_global_policy
    ADD CONSTRAINT memory_global_policy_pkey PRIMARY KEY (id);


--
-- Name: message_feedback message_feedback_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_feedback
    ADD CONSTRAINT message_feedback_pkey PRIMARY KEY (id);


--
-- Name: message_feedback message_feedback_user_id_message_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.message_feedback
    ADD CONSTRAINT message_feedback_user_id_message_id_key UNIQUE (user_id, message_id);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);


--
-- Name: regeneration_keys regeneration_keys_user_id_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regeneration_keys
    ADD CONSTRAINT regeneration_keys_user_id_key_key UNIQUE (user_id, key);


--
-- Name: semantic_facts semantic_facts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.semantic_facts
    ADD CONSTRAINT semantic_facts_pkey PRIMARY KEY (user_id, name);


--
-- Name: threads threads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.threads
    ADD CONSTRAINT threads_pkey PRIMARY KEY (user_id, thread_id);


--
-- Name: user_memory_policy user_memory_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_memory_policy
    ADD CONSTRAINT user_memory_policy_pkey PRIMARY KEY (user_id);


--
-- Name: idx_chat_attachments_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_attachments_expires ON public.chat_attachments USING btree (expires_at);


--
-- Name: idx_chat_attachments_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_attachments_thread ON public.chat_attachments USING btree (thread_id, created_at);


--
-- Name: idx_conversations_legacy_thread_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_conversations_legacy_thread_id ON public.conversations USING btree (legacy_thread_id) WHERE (legacy_thread_id IS NOT NULL);


--
-- Name: idx_conversations_user_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conversations_user_updated ON public.conversations USING btree (user_id, updated_at DESC);


--
-- Name: idx_episodic_user_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_episodic_user_thread ON public.episodic_events USING btree (user_id, thread_id, ts);


--
-- Name: idx_episodic_user_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_episodic_user_type ON public.episodic_events USING btree (user_id, type);


--
-- Name: idx_eval_cases_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_eval_cases_status ON public.eval_cases USING btree (status, created_at);


--
-- Name: idx_feedback_review_events_feedback; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_feedback_review_events_feedback ON public.feedback_review_events USING btree (feedback_id, created_at);


--
-- Name: idx_jobs_crawled; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_crawled ON public.jobs USING btree (crawled_at DESC);


--
-- Name: idx_message_feedback_user_thread; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_message_feedback_user_thread ON public.message_feedback USING btree (user_id, thread_id, updated_at DESC);


--
-- Name: auth_refresh_sessions auth_refresh_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_refresh_sessions
    ADD CONSTRAINT auth_refresh_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.auth_accounts(id) ON DELETE CASCADE;


--
-- Name: conversation_turns conversation_turns_thread_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_turns
    ADD CONSTRAINT conversation_turns_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES public.conversations(id);


--
-- Name: eval_cases eval_cases_source_feedback_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.eval_cases
    ADD CONSTRAINT eval_cases_source_feedback_id_fkey FOREIGN KEY (source_feedback_id) REFERENCES public.message_feedback(id) ON DELETE CASCADE;


--
-- Name: feedback_reviews feedback_reviews_feedback_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_reviews
    ADD CONSTRAINT feedback_reviews_feedback_id_fkey FOREIGN KEY (feedback_id) REFERENCES public.message_feedback(id) ON DELETE CASCADE;


--
-- Name: feedback_snapshots feedback_snapshots_feedback_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.feedback_snapshots
    ADD CONSTRAINT feedback_snapshots_feedback_id_fkey FOREIGN KEY (feedback_id) REFERENCES public.message_feedback(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--
"""


def upgrade() -> None:
    """逐条执行快照 DDL；先剔除注释行（pg_dump 注释内含分号会破坏切分）。"""
    bind = op.get_bind()
    lines = [ln for ln in SCHEMA_SQL.splitlines() if not ln.strip().startswith("--")]
    for statement in chr(10).join(lines).split(";"):
        s = statement.strip()
        if s:
            bind.exec_driver_sql(s)


def downgrade() -> None:
    """baseline 不提供回滚（重建请重新 upgrade 或从备份恢复）。"""
    raise NotImplementedError("baseline 无 downgrade")
