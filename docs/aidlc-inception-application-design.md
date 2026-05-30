# Application Design - Detailed Steps
*Source: [awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows) — `aidlc-rules/aws-aidlc-rule-details/inception/application-design.md`*

---

## Purpose
**High-level component identification and service layer design**

Application Design focuses on:
- Identifying main functional components and their responsibilities
- Defining component interfaces (not detailed business logic)
- Designing service layer for orchestration
- Establishing component dependencies and communication patterns

**Note**: Detailed business logic design happens later in Functional Design (per-unit, CONSTRUCTION phase)

## Prerequisites
- Workspace Detection must be complete
- Requirements Analysis recommended (provides functional context)
- User Stories recommended (user stories guide design decisions)
- Execution plan must indicate Application Design stage should execute

## Step-by-Step Execution

### Step 1: Analyze Context
- Read `aidlc-docs/inception/requirements/requirements.md` and `aidlc-docs/inception/user-stories/stories.md`
- Identify key business capabilities and functional areas
- Determine design scope and complexity

### Step 2: Create Application Design Plan
- Generate plan with checkboxes [] for application design
- Focus on components, responsibilities, methods, business rules, and services

### Step 3: Include Mandatory Design Artifacts in Plan
- [ ] Generate `components.md` with component definitions and high-level responsibilities
- [ ] Generate `component-methods.md` with method signatures (business rules detailed later in Functional Design)
- [ ] Generate `services.md` with service definitions and orchestration patterns
- [ ] Generate `component-dependency.md` with dependency relationships and communication patterns
- [ ] Validate design completeness and consistency

### Step 4: Generate Context-Appropriate Questions

**DIRECTIVE**: Analyze the requirements and stories to generate questions relevant to THIS specific application design. When in doubt about applicability, ask the question rather than skipping it — overconfidence leads to poor outcomes.

**Question categories to evaluate (ALL)**:
- **Component Identification** — component boundaries, organization, and grouping strategies
- **Component Methods** — method signatures, input/output expectations, interface contracts (detailed business rules come later)
- **Service Layer Design** — service orchestration, boundaries, and coordination patterns
- **Component Dependencies** — communication patterns, dependency management, and coupling concerns
- **Design Patterns** — architectural style preferences, pattern choices, and design constraints

### Step 5: Store Application Design Plan
- Save as `aidlc-docs/inception/plans/application-design-plan.md`
- Include all [Answer]: tags for user input

### Step 6: Request User Input
- Ask user to fill [Answer]: tags directly in the plan document

### Step 7: Collect Answers
- Wait for ALL [Answer]: tags to be completed

### Step 8: ANALYZE ANSWERS (MANDATORY)
Before proceeding, review ALL answers for:
- Vague or ambiguous responses: "mix of", "somewhere between", "not sure", "depends"
- Undefined criteria or terms
- Contradictory answers
- Missing design details
- Answers combining options without clear decision rules

### Step 9: MANDATORY Follow-up Questions
If analysis reveals ANY ambiguous answers:
- Add specific follow-up questions to the plan using [Answer]: tags
- DO NOT proceed to approval until all ambiguities resolved

### Step 10: Generate Application Design Artifacts

Create `aidlc-docs/inception/application-design/components.md` with:
- Component name and purpose
- Component responsibilities
- Component interfaces

Create `aidlc-docs/inception/application-design/component-methods.md` with:
- Method signatures for each component
- High-level purpose of each method
- Input/output types
- Note: Detailed business rules defined in Functional Design (CONSTRUCTION phase)

Create `aidlc-docs/inception/application-design/services.md` with:
- Service definitions and responsibilities
- Service interactions and orchestration

Create `aidlc-docs/inception/application-design/component-dependency.md` with:
- Dependency matrix showing relationships
- Communication patterns between components
- Data flow diagrams

Create `aidlc-docs/inception/application-design/application-design.md` consolidating all the above.

### Step 11: Log Approval
- Log approval prompt with timestamp in `aidlc-docs/audit.md`

### Step 12: Present Completion Message

```markdown
# 🏗️ Application Design Complete

> **📋 REVIEW REQUIRED:**
> Please examine the application design artifacts at: `aidlc-docs/inception/application-design/`

> **🚀 WHAT'S NEXT?**
> 🔧 **Request Changes** - Ask for modifications to the application design if required
> ✅ **Approve & Continue** - Approve design and proceed to **[Units Generation/CONSTRUCTION PHASE]**
```

### Step 13: Wait for Explicit Approval
- Do not proceed until user explicitly approves
- If user requests changes, update and repeat

### Step 14: Record Approval Response
- Log response with timestamp in `aidlc-docs/audit.md`

### Step 15: Update Progress
- Mark Application Design stage complete in `aidlc-docs/aidlc-state.md`
