| date | step | decision | reason |
| --- | --- | --- | --- |
| 2026-11-20 | SYNC7 | `GET /clients/{id}/groups` now returns each group's `id` (GroupNode.id, queries.groups_tree). | The Tally masters PUT needs `target_group_id`; the screen could only keep the suggested group. Read-only, additive; the integration assertion in test_api.py was adjusted for the new key (not run: no DB tests in this task). |
| 2026-11-20 | SYNC7 | Frontend adapts to the backend for `GET /tally/imports` (rows have `id`, no `report`) instead of changing the router. | The route returns the stored row as is; the screen only needs id, status, company, date. |
| 2026-11-20 | SYNC7 | `GET .../bank/lines/{id}/suggestion` is sent with X-User. | The router requires an actor (it can log a model call); without it the call answered 400 invalid_actor. |
