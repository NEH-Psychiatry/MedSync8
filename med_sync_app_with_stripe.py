import os

import streamlit as st
from datetime import datetime

from sync_calculator import calculate_sync_quantities


def init_supabase():
    from supabase import create_client, Client
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        st.error("Missing SUPABASE_URL or SUPABASE_KEY environment variables. Please configure them before running.")
        st.stop()
    return create_client(url, key)


def show_login(supabase):
    st.title("Login to Medication Sync App")
    login_tab, signup_tab = st.tabs(["Login", "Sign Up"])

    with login_tab:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login"):
            if not email or not password:
                st.error("Please enter both email and password.")
            else:
                try:
                    user = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    if user:
                        st.session_state['user'] = user
                        st.success("Logged in successfully!")
                        st.rerun()
                except Exception:
                    st.error("Login failed. Please check your credentials.")

    with signup_tab:
        new_email = st.text_input("New Email", key="signup_email")
        new_password = st.text_input("New Password", type="password", key="signup_password")
        if st.button("Sign Up"):
            if not new_email or not new_password:
                st.error("Please enter both email and password.")
            else:
                try:
                    supabase.auth.sign_up({"email": new_email, "password": new_password})
                    st.success("Sign-up successful! Please check your email to confirm.")
                except Exception:
                    st.error("Sign-up failed. Please try again.")


def show_dashboard(supabase):
    st.title("Medication Sync Calculator")

    if st.sidebar.button("Logout"):
        supabase.auth.sign_out()
        del st.session_state['user']
        st.rerun()

    if "is_premium" not in st.session_state:
        st.session_state["is_premium"] = False

    stripe_link = os.environ.get("STRIPE_PAYMENT_LINK", "")

    st.write("Free users can sync up to 2 medications.")
    if not st.session_state["is_premium"]:
        if stripe_link and stripe_link.startswith("https://"):
            st.markdown(f"[Upgrade to Premium for Unlimited Access]({stripe_link})")
        st.warning("You're currently using the free tier.")

    with st.form("med_form"):
        num_meds = st.number_input("Number of existing medications", min_value=0, max_value=10, step=1)

        meds = []
        for i in range(num_meds):
            name = st.text_input(f"Medication {i+1} Name", key=f"name_{i}")
            daily_dose = st.number_input(f"Daily Dose for Medication {i+1}", min_value=1, key=f"dose_{i}")
            remaining = st.number_input(f"Units Remaining for Medication {i+1}", min_value=0, key=f"remaining_{i}")
            meds.append({'name': name, 'daily_dose': daily_dose, 'remaining': remaining})

        st.markdown("### New Medication Details")
        new_name = st.text_input("New Medication Name", key="new_name")
        new_dose = st.number_input("New Medication Daily Dose", min_value=1, key="new_dose")
        new_med = {'name': new_name, 'daily_dose': new_dose}

        sync_date = st.date_input("Desired Sync Date")
        submitted = st.form_submit_button("Calculate")

    if submitted:
        if not st.session_state["is_premium"] and num_meds > 2:
            st.error("Upgrade to premium to sync more than 2 medications.")
            return

        result = calculate_sync_quantities(meds, new_med, sync_date.strftime("%Y-%m-%d"))
        if result:
            st.subheader("Sync Plan")
            for med in result:
                st.write(f"**{med['name']}**: {med['units_needed']} units needed to sync by {sync_date}")
        elif (sync_date - datetime.today().date()).days < 0:
            st.error("Sync date must be in the future.")


def main():
    supabase = init_supabase()

    if 'user' not in st.session_state:
        show_login(supabase)
    else:
        show_dashboard(supabase)


if __name__ == "__main__":
    main()
