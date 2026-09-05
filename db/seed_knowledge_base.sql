-- Seeds the knowledge base with the firm's actual verified facts, sourced
-- from the company brain (`AMS Capital Management/CLAUDE.md`, last updated
-- 24 August 2026, amended 5 September 2026). Run once after 001_init.sql.
-- Every agent that drafts or answers a question reads this table — if a
-- fact isn't here, the agent is instructed to say INSUFFICIENT VERIFIED
-- INFORMATION rather than invent one. Keep this in sync with CLAUDE.md by
-- hand; the two are not the same file and nothing here reads the other.

insert into knowledge_base (category, key, content) values
('company_info', 'overview',
 'A.M.S. Capital Management Holdings Ltd — independent capital advisory. Established 2022. '
 'UK holding company incorporated August 2026. Company number 17396139, registered in England '
 'and Wales. Registered office: 5th Floor, 167-169 Great Portland Street, London W1W 5PF. '
 'Contact: invest@amscapital.co.uk. Offices: London (HQ), New York, Dubai, Delhi, Singapore. '
 'The firm advises businesses and institutional partners on raising, structuring and deploying '
 'capital, from first mandate through to completion. It does not manage client money or hold '
 'client assets.'),

('company_info', 'verified_track_record',
 'Aggregate transaction and development value of mandates advised since 2022: $3.35bn. This is '
 'advisory volume — NOT funds raised, managed, or AUM, and must never be restated as either. '
 'More than 1,700 international capital partners on the database (institutions, family offices, '
 'PE/VC, lenders and strategics) — inclusion implies no commitment to invest from any of them, '
 'and no individual partner may ever be named. Mandate range: $100,000-$2bn. No fixed minimum '
 'or maximum.'),

('compliance', 'regulatory_position',
 'A.M.S. is not currently authorised by the Financial Conduct Authority. It provides corporate '
 'advisory services; where regulated activities are involved it works alongside appropriately '
 'authorised advisers and counterparties. A restructuring programme is underway and FCA '
 'authorisation forms part of the long-term strategy. If asked directly whether A.M.S. is '
 'regulated, this is the only truthful answer — never soften it, never imply otherwise. As of '
 '5 September 2026, A.M.S. also works with an FCA-authorised firm that can approve certain '
 'content under section 21(2)(b) FSMA — the mechanism for this is not yet confirmed in writing, '
 'so no content may be marked as "approved via that route" without a named contact and evidence '
 'of an actual per-item approval.'),

('compliance', 'never_claim',
 'Never state or imply capital will be raised, or that a transaction will complete. Never claim '
 'A.M.S. is regulated, authorised or FCA-registered. Never say A.M.S. will fund, lend to, or '
 'invest in a client — it advises and introduces. Never name a capital partner (aggregate only). '
 'Never use pooling language — A.M.S. does not hold, pool, manage or invest anyone''s money. '
 'Never fabricate a lead, contact, referral, figure or track-record claim. Never send an '
 'external email or make a call without a named human approving it.'),

('pricing', 'stage_one',
 'Stage One — Initial engagement: GBP 7,500 + VAT (USD 9,999 international). Covers strategic '
 'assessment, investor readiness review, investment materials and information memorandum, '
 'financial modelling, data room preparation, capital strategy. Refundable where applicable per '
 'the signed mandate and agreed engagement period.'),

('pricing', 'stage_two',
 'Stage Two — Success fee: 1.5%-5%, charged to the INVESTOR (never the client) as a brokerage '
 'fee, payable only on completion. Rate by investor access level: 1.5% Private Investor Circle, '
 '3% Select Investor, 5% Registered Investor. The business receives the agreed capital in full '
 '— lead with this, it is the strongest commercial point the firm has and it is true.'),

('process', 'documents_needed',
 'Five documents to start a mandate: (1) business plan or investment summary, (2) financial '
 'statements, 2-3 years, audited where available, (3) projections or a model, 3-5 years, (4) '
 'corporate structure and cap table, (5) raise detail — amount, use of proceeds, instrument, '
 'security, timeline. Initial review takes 24-72 hours from a complete pack. Sectors: real '
 'estate, infrastructure, energy, technology, consumer, and adjacent real-asset verticals.'),

('brand', 'house_voice',
 'Plain, declarative, unhurried, quietly confident. Short sentences. Facts instead of '
 'adjectives. State the uncomfortable thing openly rather than hiding it. Banned: exclamation '
 'marks, "reach out", "circle back", "touch base", "quick question", "I hope this email finds '
 'you well", "just following up", or any sentence that would embarrass a partner if forwarded to '
 'a prospect''s board.')

on conflict (category, key) do update set content = excluded.content, updated_at = now();
