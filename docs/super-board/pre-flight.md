# Super Board pre-flight

This checkout is the proposed implementation base for [LLM Wiki Backlog](https://github.com/users/K0stIa/projects/1). The board points to `K0stIa/llm-wiki`, base `super-board/implementation`, and pins `gpt-6.2-sol` for Codex. Merges require human approval.

## Local setup

- [✓] GitHub CLI can read the board as K0stIa. The board contains the existing tickets and standard statuses.
- [✓] Git, Codex CLI, Node.js, jq, Python, and uv are installed. The Codex launchers pass shell syntax checks.
- [✓] The snapshot has independent Git history. Its source inventory excludes access files, raw evaluation data, and repository history.
- [✓] Python dependencies are installed offline from the lock. Node dependencies are copied from the checkout that uses the same package lock.
- [✓] TypeScript, 43 focused Python tests, and 12 focused Node tests passed. The Python scope omits the case that reads the private frozen corpus.
- [✓] Git's fetch URL is configured. Push is disabled locally until approval.

## Before dispatch

- [ ] Owner has reviewed this source snapshot and approved publication of this new history to the selected GitHub destination. Only then enable push and publish the proposed base. Verify the remote base matches this checkout.
- [ ] Run cloud workers in an environment without the private corpus, access secrets, or original checkout. The stock Codex launcher can read outside its checkout. Do not launch it here while that access could reach private evaluation data.
- [ ] Run Super Board lint on Ready issue #1 from the approved runner and check its verification requirements. Issue #1's model and concurrent benchmark require Phase P execution authorization. Use synthetic verification for source changes and keep private G2 evaluation on its approved local endpoint.

Passing these setup checks does not supply G2 release evidence. Read the repository's [execution and data rules](../../CLAUDE.md) before running any evaluation.
