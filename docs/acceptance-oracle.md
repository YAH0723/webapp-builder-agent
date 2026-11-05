# Where internal acceptance conditions come from

Original input `requirements.yaml` is the business authority. Requirement descriptions
and scenario Given/When/Then define prerequisites, actions and expected outcomes.
Reference images supply visible layout/labels. Generated designs must not weaken them.

| Internal check | Authoring input | What execution establishes |
|---|---|---|
| Backend HTTP tests | Original owner scenarios, generated API method/path/request/response/P-Q contracts, relevant schema | Server meets the authored HTTP/state assertions |
| UI existence checks | Generated page/UI definitions | Authored controls/pages exist; business behavior is not established |
| Independent browser acceptance | Original YAML reread from disk, Given/When/Then, interface/schema details for locators and prerequisites | Browser actions meet authored visible/state assertions |
| Continuous journey | Selected related original requirements and interface details | Authored related actions work together and retain required state across navigation/reload |

In classic B5/B5.1, the independent author cannot read application or implementation
test sources. It may use isolated SQL Given fixtures for individual requirements.
The added journey requires prerequisite creation through the browser. In compact
B6/B6.1, the author sees all original requirements, the joint plan and image evidence,
without implementation sources; it is instructed to use browser actions rather than
direct database/API mutations.

A test that seeds an existing record and checks a list establishes listing behavior.
It cannot establish that the creation form works. Creation needs form entry,
submission, the required visible result and any required persistence assertion.
Cancellation additionally needs proof that the relevant state remains unchanged.
Case counts do not establish those assertions unless their actual code executes them.

Playwright/Node execute generated tests against real application processes and temporary
SQLite databases. Tests remain protected during app repair. Annotations require original
IDs to map to collected/passing tests, but **do not prove assertion correctness or completeness**.

The author can misunderstand text, omit a condition, use an incorrect locator or inherit
an error from generated API/UI designs. It may use the same model as implementation;
separate context is not an independent ground-truth oracle. Internal GREEN means the
authored checks passed. ARC-Bench's official tests are separate and determine official
correctness; they are not copied into internal acceptance suites.
