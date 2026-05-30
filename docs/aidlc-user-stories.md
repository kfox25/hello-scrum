# User Stories - Detailed Steps
*Source: [awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows) — `aidlc-rules/aws-aidlc-rule-details/inception/user-stories.md`*

---

## Purpose
**Convert requirements into user-centered stories with acceptance criteria**

User Stories focus on:
- Translating business requirements into user-centered narratives
- Defining clear acceptance criteria for each story
- Creating user personas that represent different stakeholder types
- Establishing shared understanding across teams
- Providing testable specifications for implementation

## Prerequisites
- Workspace Detection must be complete
- Requirements Analysis recommended
- Workflow Planning must indicate User Stories stage should execute

## Intelligent Assessment Guidelines

### High Priority Execution (ALWAYS Execute)
- **New User Features**: Any new functionality users will directly interact with
- **User Experience Changes**: Modifications to existing user workflows or interfaces
- **Multi-Persona Systems**: Applications serving different types of users
- **Customer-Facing APIs**: Services that external users or systems will consume
- **Complex Business Logic**: Requirements with multiple scenarios or business rules
- **Cross-Team Projects**: Work requiring shared understanding across multiple teams

### Medium Priority Execution (Assess Complexity)
- Backend changes with user impact
- Performance improvements with user-visible benefits
- Integration work affecting user workflows
- Data changes affecting user data, reports, or analytics
- Security enhancements affecting user authentication or permissions

### Skip Only For Simple Cases
- Pure refactoring (zero user impact)
- Isolated bug fixes (well-defined, clear scope)
- Infrastructure only
- Developer tooling
- Documentation

### Default Decision Rule
**When in doubt, include user stories AND ask clarifying questions.** The overhead of comprehensive stories is outweighed by: clearer requirements, better team alignment, improved testing criteria, reduced implementation risks.

---

# PART 1: PLANNING

## Step 1: Validate User Stories Need (MANDATORY)

Before proceeding, assess:
1. Analyze request context — user-facing vs internal-only changes, complexity, stakeholder involvement
2. Apply assessment criteria — High Priority indicators, Medium Priority complexity factors
3. Document assessment decision in `aidlc-docs/inception/plans/user-stories-assessment.md`
4. Proceed only if justified

## Step 2: Create Story Plan
- Assume the role of a product owner
- Generate a comprehensive plan with step-by-step execution checklist
- Each step and sub-step should have a checkbox []

## Step 3: Generate Context-Appropriate Questions

**DIRECTIVE**: Thoroughly analyze requirements to identify ALL areas where clarification would improve story quality. Default to asking questions when there is ANY ambiguity.

**Question categories to evaluate (ALL)**:
- **User Personas** — user types, roles, characteristics, motivations
- **Story Granularity** — level of detail, story size, breakdown approach
- **Story Format** — format preferences, template usage, documentation standards
- **Breakdown Approach** — organization method, prioritization, grouping strategies
- **Acceptance Criteria** — detail level, format, testing approach, validation methods
- **User Journeys** — user workflows, interaction patterns, experience flows
- **Business Context** — business goals, success metrics, stakeholder needs
- **Technical Constraints** — technical limitations, integration requirements, system boundaries

## Step 4: Include Mandatory Story Artifacts in Plan
- [ ] Generate `stories.md` with user stories following INVEST criteria
- [ ] Generate `personas.md` with user archetypes and characteristics
- [ ] Ensure stories are Independent, Negotiable, Valuable, Estimable, Small, Testable
- [ ] Include acceptance criteria for each story
- [ ] Map personas to relevant user stories

## Step 5: Present Story Options
Include different approaches for story breakdown:
- **User Journey-Based**: Stories follow user workflows
- **Feature-Based**: Stories organized around system features
- **Persona-Based**: Stories grouped by user types
- **Domain-Based**: Stories organized around business domains
- **Epic-Based**: Hierarchical epics with sub-stories

## Step 6: Store Story Plan
- Save as `aidlc-docs/inception/plans/story-generation-plan.md`
- Include all [Answer]: tags for user input

## Step 7: Request User Input
- Ask user to fill in all [Answer]: tags directly in the plan document

## Step 8: Collect Answers
- Wait for ALL [Answer]: tags to be completed before proceeding

## Step 9: ANALYZE ANSWERS (MANDATORY)
Review ALL answers for:
- Vague responses: "mix of", "somewhere between", "not sure", "depends", "maybe"
- Undefined criteria or terms
- Contradictory answers
- Missing generation details
- Answers combining options without clear decision rules

## Step 10: MANDATORY Follow-up Questions
If analysis reveals ANY ambiguous answers:
- Create clarification questions file using [Answer]: tags
- DO NOT proceed until ALL ambiguities resolved
- Examples:
  - "You mentioned 'mix of A and B' — what specific criteria determine when to use A vs B?"
  - "You said 'somewhere between A and B' — can you define the exact middle ground?"
  - "You indicated 'not sure' — what additional information would help you decide?"

## Steps 11–14: Approval
- Avoid implementation details at this stage
- Log approval prompt in `aidlc-docs/audit.md`
- Wait for explicit plan approval
- Record approval response with timestamp

---

# PART 2: GENERATION

## Step 15–18: Execute Plan
- Load `story-generation-plan.md`
- Execute each uncompleted step sequentially
- Mark [x] after each completed step
- Update `aidlc-state.md`

## Step 19–23: Completion and Approval
- Log approval prompt in audit.md
- Present completion message:

```markdown
# 📚 User Stories Complete
```

- Present artifacts at `aidlc-docs/inception/user-stories/stories.md` and `personas.md`
- Wait for explicit approval
- Record approval response
- Mark User Stories stage complete in `aidlc-state.md`

---

# CRITICAL RULES

## Planning Phase Rules
- Context-appropriate questions only
- Mandatory answer analysis for ambiguities
- No proceeding with ambiguity
- Explicit approval required before generation

## Generation Phase Rules
- NO HARDCODED LOGIC — only execute what's in the story plan
- FOLLOW PLAN EXACTLY
- UPDATE CHECKBOXES immediately after each step
- USE APPROVED METHODOLOGY
- VERIFY COMPLETION before proceeding

## Completion Criteria
- All planning questions answered and ambiguities resolved
- Story plan explicitly approved
- All steps marked [x]
- `stories.md` and `personas.md` generated
- Generated stories explicitly approved
- Stories verified and ready for next stage

---

## Hello Scrum Mapping

In hello-scrum, User Stories are generated during the Elaborate step of the Inception page. The `story` field stores the "As a... I want... so that..." text. The `acceptance_criteria` array stores the AC items. Stories are the execution contracts for the agent.
