"""One-off generator for the 5 synthetic resume PDF fixtures used by tests.

Run manually whenever the fixture resumes need to change:

    uv run python scripts/generate_resume_fixtures.py

Not part of the test suite or runtime — reportlab is a dev-only dependency.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "resumes"

RESUMES: dict[str, list[str]] = {
    "new_grad_frontend.pdf": [
        "Priya Nair",
        "priya.nair@example.com | linkedin.com/in/priyanair | github.com/priyanair",
        "",
        "SUMMARY",
        "Recent CS graduate focused on frontend engineering and accessible UI design.",
        "",
        "EDUCATION",
        "B.S. Computer Science, University of Washington, 2024, GPA 3.7",
        "",
        "EXPERIENCE",
        "Frontend Engineering Intern, Cedarwood Labs, Jun 2023 - Aug 2023",
        "- Built reusable React components used across 3 internal dashboards",
        "- Improved Lighthouse accessibility score from 71 to 94",
        "",
        "Teaching Assistant, University of Washington, Sep 2022 - Jun 2023",
        "- Led weekly sections for Intro to Web Development (120 students)",
        "",
        "PROJECTS",
        "Recipe Finder - React + TypeScript app with Spoonacular API integration",
        "- Open source, 40+ GitHub stars",
        "",
        "SKILLS",
        "JavaScript, TypeScript, React, CSS, HTML, Git, Figma",
    ],
    "mid_backend.pdf": [
        "Marcus Webb",
        "marcus.webb@example.com | github.com/marcuswebb",
        "",
        "SUMMARY",
        "Backend engineer with 4 years building distributed systems in Python and Go.",
        "",
        "EXPERIENCE",
        "Backend Engineer, Lighthouse Freight, Mar 2021 - Present",
        "- Designed event-driven order pipeline handling 2M events/day with Kafka",
        "- Migrated monolith service to Go microservices, cut p99 latency 40%",
        "- Mentored 2 junior engineers",
        "",
        "Software Engineer, DataPort Inc, Jul 2019 - Feb 2021",
        "- Built REST APIs in Django serving internal analytics tools",
        "- Wrote integration tests raising coverage from 52% to 88%",
        "",
        "EDUCATION",
        "B.S. Computer Engineering, Georgia Tech, 2019",
        "",
        "SKILLS",
        "Python, Go, Kafka, PostgreSQL, Docker, Kubernetes, AWS, Django",
    ],
    "senior_ml.pdf": [
        "Dr. Elena Castillo",
        "elena.castillo@example.com | linkedin.com/in/elenacastillo",
        "",
        "SUMMARY",
        "Senior ML engineer with 7 years shipping recommendation and ranking systems.",
        "",
        "EXPERIENCE",
        "Senior Machine Learning Engineer, Northstar Retail, Jan 2020 - Present",
        "- Led redesign of product ranking model, lifting conversion 8%",
        "- Built feature store serving 200+ features to 5 downstream models",
        "- Own the team's experimentation and offline eval framework",
        "",
        "Machine Learning Engineer, Northstar Retail, Jun 2017 - Dec 2019",
        "- Built click-through-rate prediction model using gradient boosted trees",
        "",
        "EDUCATION",
        "M.S. Machine Learning, Carnegie Mellon University, 2017",
        "B.S. Statistics, UC Davis, 2015",
        "",
        "PROJECTS",
        "OpenRank - open source learning-to-rank library, 300+ GitHub stars",
        "",
        "SKILLS",
        "Python, PyTorch, TensorFlow, SQL, Spark, Airflow, MLflow, A/B testing",
    ],
    "staff_infra.pdf": [
        "Jonah Kessler",
        "jonah.kessler@example.com | github.com/jkessler",
        "",
        "SUMMARY",
        "Staff infrastructure engineer, 10+ years on platform reliability and scaling.",
        "",
        "EXPERIENCE",
        "Staff Infrastructure Engineer, Brightline Cloud, Feb 2018 - Present",
        "- Drove migration of 400+ services from VMs to Kubernetes",
        "- Designed multi-region failover reducing incident MTTR by 60%",
        "- Set platform-wide SLOs and on-call standards adopted org-wide",
        "",
        "Senior Site Reliability Engineer, Brightline Cloud, Apr 2014 - Jan 2018",
        "- Built internal deploy pipeline used by 50+ teams",
        "",
        "Systems Engineer, Vantage Networks, Jun 2011 - Mar 2014",
        "- Operated bare-metal infrastructure for a 10k-node fleet",
        "",
        "EDUCATION",
        "B.S. Computer Science, University of Texas at Austin, 2011",
        "",
        "SKILLS",
        "Kubernetes, Terraform, Go, AWS, GCP, Prometheus, Linux, networking",
    ],
    "career_switcher_data.pdf": [
        "Aisha Thompson",
        "aisha.thompson@example.com | linkedin.com/in/aishathompson",
        "",
        "SUMMARY",
        "Former high school math teacher transitioning into data analytics; completed",
        "a part-time data analytics bootcamp while teaching full-time.",
        "",
        "EXPERIENCE",
        "High School Math Teacher, Riverside Unified School District, Aug 2017 - Jun 2024",
        "- Taught AP Statistics and Algebra II to 150+ students annually",
        "- Built a spreadsheet-based grade analytics tool adopted by 6 teachers",
        "",
        "Data Analytics Bootcamp Capstone, Sparkline Analytics Bootcamp, 2024",
        "- Analyzed 5 years of city transit data to identify ridership trends in SQL/Python",
        "- Presented findings to a panel of working data analysts",
        "",
        "EDUCATION",
        "Data Analytics Certificate, Sparkline Analytics Bootcamp, 2024",
        "B.A. Mathematics, Florida State University, 2017",
        "",
        "PROJECTS",
        "Transit Ridership Dashboard - Streamlit + pandas dashboard of public transit data",
        "",
        "SKILLS",
        "SQL, Python, pandas, Excel, Tableau, statistics",
    ],
}


def _render(path: Path, lines: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER
    x = 0.75 * inch
    y = height - 0.75 * inch
    c.setFont("Helvetica", 11)
    for line in lines:
        if y < 0.75 * inch:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = height - 0.75 * inch
        c.drawString(x, y, line)
        y -= 0.22 * inch
    c.save()


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for filename, lines in RESUMES.items():
        _render(FIXTURES_DIR / filename, lines)
        print(f"wrote {FIXTURES_DIR / filename}")


if __name__ == "__main__":
    main()
