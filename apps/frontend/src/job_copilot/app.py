import asyncio

import streamlit as st

from job_copilot.agent import JobAgent
from job_copilot.config import get_settings
from job_copilot.domain import ApplicationStage, JobSearchFilters, ProfilePatch
from job_copilot.factory import build_service
from job_copilot.identity import actor_from_headers

st.set_page_config(page_title="AI Job Hunting Copilot", page_icon="ðŸ’¼", layout="wide")


def run(coro):
    return asyncio.run(coro)


@st.cache_resource
def service():
    return build_service()


def actor():
    headers = {key: value for key, value in st.context.headers.items()}
    return actor_from_headers(headers)


try:
    current_actor = actor()
except PermissionError:
    st.error("This app must run through Databricks Apps so it can identify the signed-in user.")
    st.stop()

st.title("AI Job Hunting Copilot")
st.caption("Jobs via Remote OK Â· saves and updates only your personal Lakebase pipeline")
tabs = st.tabs(["Find jobs", "Profile", "Pipeline"])

with tabs[0]:
    query = st.text_input(
        "What role are you looking for?", placeholder="Remote data engineer working with Spark"
    )
    remote_only = st.checkbox("Remote only")
    if st.button("Search jobs", type="primary") and query:
        st.session_state["jobs"] = run(
            service().search_jobs(current_actor, query, JobSearchFilters(remote_only=remote_only))
        )
    for job in st.session_state.get("jobs", []):
        with st.container(border=True):
            st.subheader(job.title)
            st.write(
                f"{job.company or 'Unknown company'} Â· {job.location or 'Location unavailable'} Â· Match {job.score:.0%}"
            )
            if job.matched_skills:
                st.caption("Matched: " + ", ".join(job.matched_skills))
            st.write(job.description[:500] + ("â€¦" if len(job.description) > 500 else ""))
            left, right = st.columns(2)
            with left:
                if job.url:
                    st.link_button("View source", job.url)
            with right:
                stage = st.selectbox(
                    "Pipeline stage",
                    [item.value for item in ApplicationStage],
                    key=f"stage-{job.posting_id}",
                )
                if st.button("Save / update", key=f"save-{job.posting_id}"):
                    run(
                        service().set_application_stage(current_actor, job, ApplicationStage(stage))
                    )
                    st.success("Pipeline updated.")
    st.divider()
    message = st.chat_input("Ask about matches, your pipeline, or request a tailored snippet")
    if message:
        with st.chat_message("user"):
            st.write(message)
        with st.chat_message("assistant"):
            st.write(run(JobAgent(service(), get_settings()).respond(current_actor, message)))

with tabs[1]:
    profile = run(service().repository.get_profile(current_actor))
    with st.form("profile"):
        roles = st.text_input("Target roles (comma-separated)", ", ".join(profile.target_roles))
        locations = st.text_input(
            "Preferred locations (comma-separated)", ", ".join(profile.preferred_locations)
        )
        skills = st.text_input("Skills (comma-separated)", ", ".join(profile.skills))
        remote = st.selectbox(
            "Work preference",
            ["", "remote", "hybrid", "onsite"],
            index=["", "remote", "hybrid", "onsite"].index(profile.remote_preference or ""),
        )
        summary = st.text_area("Experience summary", value=profile.resume_excerpt)
        if st.form_submit_button("Save profile"):
            run(
                service().update_profile(
                    current_actor,
                    ProfilePatch(
                        target_roles=[item.strip() for item in roles.split(",") if item.strip()],
                        preferred_locations=[
                            item.strip() for item in locations.split(",") if item.strip()
                        ],
                        remote_preference=remote or None,
                        resume_text=summary or None,
                    ),
                    [item.strip() for item in skills.split(",") if item.strip()],
                )
            )
            st.success("Profile saved.")

with tabs[2]:
    applications = run(service().repository.list_applications(current_actor))
    stale = run(service().repository.list_stale_applications(current_actor))
    if stale:
        st.warning(f"{len(stale)} application(s) have not been updated in at least seven days.")
    st.dataframe(applications, use_container_width=True, hide_index=True)

