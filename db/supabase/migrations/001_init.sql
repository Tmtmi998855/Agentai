-- Ah!There 초기 스키마 (Supabase / PostgreSQL 15+)
-- 기획서 v2 초안 대비 수정 사항은 docs/PRD_v2_hybrid.md "5. 데이터베이스" 참고.

create extension if not exists pgcrypto;

-- 1. 유저 및 영업 프로필 (템플릿 ID만 저장, 라벨은 app/data/sales_templates.json에서 해석)
create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  messenger_type text not null check (messenger_type in ('telegram', 'kakao', 'imessage', 'web')),
  messenger_user_id text not null check (char_length(messenger_user_id) between 1 and 100),
  template_version text not null,
  category_id text not null,
  product_id text not null,
  value_prop_ids text[] not null check (cardinality(value_prop_ids) between 1 and 3),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- 메신저가 다르면 같은 숫자 ID가 겹칠 수 있으므로 (메신저, ID) 조합으로 유일
  unique (messenger_type, messenger_user_id)
);

-- 2. 기업 분석 리포트
create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  target_company text not null check (char_length(target_company) between 1 and 100),
  status text not null check (status in ('SUCCESS', 'INSUFFICIENT_EVIDENCE', 'ENTITY_AMBIGUOUS')),
  company_summary text not null,
  industry_summary text not null,
  questions jsonb not null,          -- [{type, question, intent, evidence_ids, value_prop_id, grounded}] x3
  sources jsonb not null default '[]'::jsonb,  -- 확정 출처만 [{evidence_id, claim, publisher, url, published_at, source_tier, scope}]
  briefing jsonb not null,           -- 전체 BriefingObject (웹 대시보드 상세 렌더링용)
  meeting_memo text,                 -- 웹 대시보드에서 영업사원이 작성하는 미팅 메모
  created_at timestamptz not null default now()
);

create index if not exists reports_user_created_idx on public.reports (user_id, created_at desc);

-- updated_at 자동 갱신
create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists users_set_updated_at on public.users;
create trigger users_set_updated_at before update on public.users
  for each row execute function public.set_updated_at();

-- 3. RLS: anon/authenticated 키로는 아무것도 읽거나 쓸 수 없게 잠근다.
--    백엔드(MCP 서버)와 Next.js 서버 컴포넌트만 service_role 키로 접근한다.
--    (service_role은 RLS를 우회하므로 별도 정책이 필요 없다.)
alter table public.users enable row level security;
alter table public.reports enable row level security;
