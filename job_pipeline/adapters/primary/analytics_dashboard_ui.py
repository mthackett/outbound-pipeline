"""Dedicated Analytics Dashboard view for Pipeline Tracker v1.5.2."""

from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st

from job_pipeline.domain.services import PipelineKPIService


def render_analytics_dashboard_view(
    opportunities: List[Dict[str, Any]],
    instance_cfg=None
):
    """
    Renders the dedicated Analytics Dashboard view.
    Accessible via the 5th KPI element in Pipeline Tracker.
    """
    # Header and Return button
    col_nav1, col_nav2 = st.columns([1.5, 4])
    with col_nav1:
        if st.button("⬅️ Return to Pipeline Tracker", key="btn_return_from_dash", use_container_width=True):
            st.session_state.in_dashboard_view = False
            st.rerun()

    st.markdown("## 📈 Pipeline Analytics Dashboard")
    st.caption("Detailed conversion funnels, source attribution, staleness diagnostics, and application trends.")

    # Dashboard Controls Toolbar
    st.markdown("---")
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1.5, 1.5, 1.5])
    with col_ctrl1:
        source_filter = st.selectbox(
            "Filter Source",
            ["All", "Outbound", "Inbound"],
            index=0,
            key="dash_filter_source"
        )
    with col_ctrl2:
        date_range_filter = st.selectbox(
            "Date Range",
            ["All Time", "Last 7 Days", "Last 30 Days", "Last 90 Days"],
            index=0,
            key="dash_filter_date_range"
        )
    with col_ctrl3:
        initial_thresh = getattr(instance_cfg, "stale_threshold_days", 7) or 7
        stale_threshold = st.number_input(
            "Stale Inactivity Threshold (Days)",
            min_value=1,
            max_value=90,
            value=initial_thresh,
            step=1,
            key="dash_stale_threshold"
        )

    # Compute centralized metrics
    dash_metrics = PipelineKPIService.calculate_analytics_dashboard_metrics(
        opportunities=opportunities,
        stale_threshold_days=stale_threshold,
        source_filter=source_filter,
        date_range_filter=date_range_filter
    )

    ov = dash_metrics["overview"]
    sp = dash_metrics["source_performance"]
    fn = dash_metrics["funnel"]
    oh = dash_metrics["opportunity_health"]
    st_data = dash_metrics["strategy"]
    rp = dash_metrics["resume_performance"]
    tr = dash_metrics["trends"]

    # 1. Overview Section
    st.markdown("### 🔍 Overview")
    ov1, ov2, ov3, ov4, ov5, ov6, ov7 = st.columns(7)
    ov1.metric("Total Tracked", ov["total_tracked"])
    ov2.metric("Outbound Opps", ov["total_outbound"])
    ov3.metric("Inbound Leads", ov["total_inbound"])
    ov4.metric("Apps Submitted", ov["applications_submitted"])
    ov5.metric("Interviews", ov["interviews_total"])
    ov6.metric("Active Pipeline", ov["active_total"])
    ov7.metric(f"Stale (≥{stale_threshold}d)", ov["stale_total"])

    st.markdown("---")

    # 2. Source Performance Section
    st.markdown("### 🎯 Source Performance & Conversion Integrity")
    st.caption("Accurate conversion rates calculated using source-specific denominators (no blended distortion).")

    col_sp_out, col_sp_in = st.columns(2)
    with col_sp_out:
        with st.container(border=True):
            st.markdown("##### 📤 Outbound Applications")
            st.caption("Submitted applications from direct job postings.")
            m_o1, m_o2, m_o3 = st.columns(3)
            m_o1.metric("Submitted", sp["outbound"]["submitted"])
            m_o2.metric("Interviews", sp["outbound"]["interviewed"])
            m_o3.metric("Conv. Rate", f"{sp['outbound']['conversion_pct']}%")

            st.markdown(
                f"<div style='font-size: 0.88rem; color: #94A3B8; margin-top: 6px;'>"
                f"Application-to-Interview Ratio: <b style='color: #818CF8;'>{sp['outbound']['ratio']}</b> "
                f"(Active: <b style='color: #F8FAFC;'>{sp['outbound']['active']}</b> · "
                f"Stale: <b style='color: #FCD34D;'>{sp['outbound']['stale']}</b>)"
                f"</div>",
                unsafe_allow_html=True
            )

    with col_sp_in:
        with st.container(border=True):
            st.markdown("##### 📥 Inbound Leads")
            st.caption("Recruiter outreaches, network leads, and agency inquiries.")
            m_i1, m_i2, m_i3 = st.columns(3)
            m_i1.metric("Tracked Leads", sp["inbound"]["tracked"])
            m_i2.metric("Interviews", sp["inbound"]["interviewed"])
            m_i3.metric("Conv. Rate", f"{sp['inbound']['conversion_pct']}%")

            st.markdown(
                f"<div style='font-size: 0.88rem; color: #94A3B8; margin-top: 6px;'>"
                f"Lead-to-Interview Ratio: <b style='color: #34D399;'>{sp['inbound']['ratio']}</b> "
                f"(Active: <b style='color: #F8FAFC;'>{sp['inbound']['active']}</b> · "
                f"Stale: <b style='color: #FCD34D;'>{sp['inbound']['stale']}</b>)"
                f"</div>",
                unsafe_allow_html=True
            )

    st.markdown("---")

    # 3. Application Funnel & Progression
    st.markdown("### 🌪️ Application Funnel Progression")
    col_fn1, col_fn2 = st.columns(2)
    with col_fn1:
        st.markdown("**Outbound Application Funnel**")
        st.markdown(
            f"""
            <div style="background: #0F172A; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-size: 0.86rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                    <span style="color: #94A3B8;">1. Total Outbound Tracked:</span>
                    <b style="color: #F8FAFC;">{fn['outbound']['tracked']}</b>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                    <span style="color: #94A3B8;">2. Applications Submitted:</span>
                    <b style="color: #60A5FA;">{fn['outbound']['submitted']}</b>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                    <span style="color: #94A3B8;">3. Positive Interest Reached:</span>
                    <b style="color: #A78BFA;">{fn['outbound']['interest']} (Apps/Interest: {fn['outbound']['app_to_interest_ratio']})</b>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #94A3B8;">4. Interview Stages Reached:</span>
                    <b style="color: #34D399;">{fn['outbound']['interviewed']} (Apps/Interview: {fn['outbound']['app_to_interview_ratio']})</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_fn2:
        st.markdown("**Inbound Lead Progression**")
        st.markdown(
            f"""
            <div style="background: #0F172A; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-size: 0.86rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                    <span style="color: #94A3B8;">1. Inbound Leads Tracked:</span>
                    <b style="color: #F8FAFC;">{fn['inbound']['tracked']}</b>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                    <span style="color: #94A3B8;">2. Interview Stages Reached:</span>
                    <b style="color: #34D399;">{fn['inbound']['interviewed']} (Lead/Interview: {fn['inbound']['opp_to_interview_ratio']})</b>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #94A3B8;">3. Currently Active Leads:</span>
                    <b style="color: #38BDF8;">{fn['inbound']['active']}</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("---")

    # 4. Opportunity Health & Staleness
    st.markdown("### 🩺 Opportunity Health Diagnostics")
    avg_days = oh["avg_days_since_activity"]
    avg_str = f"{avg_days} days" if avg_days is not None else "N/A"

    col_oh1, col_oh2 = st.columns([1, 2])
    with col_oh1:
        with st.container(border=True):
            st.metric("Avg Inactivity (Open Opps)", avg_str)
            st.metric(f"Stale Opportunities (≥{stale_threshold}d)", oh["stale_total"])
            st.caption(f"Staleness clock is based on meaningful activities (stage changes, timestamped notes, outreach) and excludes background refreshes.")

    with col_oh2:
        st.markdown(f"**Stale Breakdown by Stage & Source**")
        if oh["stale_by_stage_source"]:
            stale_rows_html = "".join([
                f"""<tr style="border-bottom: 1px solid #334155; color: #F8FAFC;">
                    <td style="padding: 6px 10px;">`{stg}`</td>
                    <td style="text-align: right; padding: 6px 10px;">{counts['Outbound']}</td>
                    <td style="text-align: right; padding: 6px 10px;">{counts['Inbound']}</td>
                    <td style="text-align: right; padding: 6px 10px; font-weight: 700; color: #FCD34D;">{counts['Total']}</td>
                </tr>"""
                for stg, counts in oh["stale_by_stage_source"].items()
            ])
            st.markdown(
                f"""
                <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem; background: #0F172A; border: 1px solid #334155; border-radius: 6px;">
                    <thead>
                        <tr style="border-bottom: 1px solid #334155; color: #94A3B8;">
                            <th style="text-align: left; padding: 6px 10px;">Stage</th>
                            <th style="text-align: right; padding: 6px 10px;">Outbound</th>
                            <th style="text-align: right; padding: 6px 10px;">Inbound</th>
                            <th style="text-align: right; padding: 6px 10px;">Total Stale</th>
                        </tr>
                    </thead>
                    <tbody>
                        {stale_rows_html}
                    </tbody>
                </table>
                """,
                unsafe_allow_html=True
            )
        else:
            st.info(f"🎉 No stale opportunities found exceeding the {stale_threshold}-day inactivity threshold.")

    if oh["stale_records"]:
        with st.expander(f"📋 View All {len(oh['stale_records'])} Stale Opportunities", expanded=False):
            st.dataframe(
                [
                    {
                        "Opportunity": r["display_name"],
                        "Source": r["source"],
                        "Stage": r["status"],
                        "Days Inactive": f"{r['days_elapsed']}d",
                        "Last Activity Date": r["last_activity_date"].strftime("%Y-%m-%d") if r["last_activity_date"] else "Missing",
                        "Activity Type": r["last_activity_source"]
                    }
                    for r in oh["stale_records"]
                ],
                use_container_width=True,
                hide_index=True
            )

    st.markdown("---")

    # 5. Application Strategy & Resume Performance
    col_str, col_res = st.columns(2)
    with col_str:
        st.markdown("### ♟️ Application Strategy")
        st.caption("Submitted outbound applications by strategic tier.")
        st.dataframe(
            [
                {
                    "Category": r["category"],
                    "Submitted": r["submitted"],
                    "Interviewed": r["interviewed"],
                    "Active": r["active"],
                    "Apps/Interview": r["conversion_ratio"]
                }
                for r in st_data["rows"]
            ],
            use_container_width=True,
            hide_index=True
        )

    with col_res:
        st.markdown("### 📑 Resume Performance")
        st.caption("Outcomes grouped by normalized resume variant.")
        st.dataframe(
            [
                {
                    "Variant": r["variant"],
                    "Tracked": r["tracked"],
                    "Applied": r["applied"],
                    "Active": r["active"],
                    "Interviewed": r["interviewed"],
                    "Apps/Interview": r["apps_per_interview"]
                }
                for r in rp["variant_rows"]
            ],
            use_container_width=True,
            hide_index=True
        )

    # 6. Activity Trends
    st.markdown("---")
    st.markdown("### 📅 Activity Trends")
    st.caption("Application and interview volume over time using verified activity dates.")
    if tr["rows"]:
        st.dataframe(
            [
                {
                    "Month": r["month"],
                    "Outbound Submitted": r["outbound_applied"],
                    "Inbound Leads": r["inbound_leads"],
                    "Interviews Reached": r["interviews"]
                }
                for r in tr["rows"]
            ],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No dated activity events available for timeline display.")
