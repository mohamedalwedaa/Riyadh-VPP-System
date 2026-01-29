import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import time

# ---------------------------------------------------------
# 1. إعدادات الصفحة (System Configuration)
# ---------------------------------------------------------
st.set_page_config(layout="wide", page_title="Riyadh VPP Command Center", page_icon="⚡", initial_sidebar_state="expanded")

# [Visual Styling]: تصميم احترافي للوضع النهاري (Corporate Light Theme)
st.markdown("""
<style>
    /* تحسين الخلفية والخطوط */
    .stApp { background-color: #FAFAFA; color: #000000; }
    
    /* تحسين ألوان العدادات لتكون مقروءة على الأبيض */
    div[data-testid="stMetricValue"] { 
        color: #00C853 !important; /* أخضر غامق مريح للعين */
        font-family: 'Segoe UI', sans-serif;
        font-weight: 700 !important;
    }
    
    div[data-testid="stMetricLabel"] {
        color: #444444 !important; /* رمادي غامق للعناوين */
    }

    /* البطاقات */
    .kpi-card { 
        background-color: #FFFFFF; 
        border: 1px solid #E0E0E0; 
        padding: 20px; 
        border-radius: 8px; 
        text-align: center; 
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    
    /* الأزرار */
    div[data-testid="stButton"] > button {
        border-radius: 6px;
        font-weight: bold;
        border: 1px solid #00C853;
        color: #00C853;
        background-color: white;
    }
    div[data-testid="stButton"] > button:hover {
        background-color: #00C853;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. الثوابت والمعايير الهندسية (Engineering Constants)
# ---------------------------------------------------------
AVG_CHARGER_CAPACITY_KW = 8.5 
CHARGING_CONCURRENCY_FACTOR = 0.85 
INVERTER_EFFICIENCY = 0.95 
GRID_VOLTAGE_LIMIT_MW = 250.0 

# تعريف أوزان الأحياء
ZONE_WEIGHTS = {
    "Al-Olaya (Business)": {"load": 0.35, "ev_density": 0.40, "lat": 24.69, "lon": 46.68},
    "Al-Malqa (North)":    {"load": 0.25, "ev_density": 0.30, "lat": 24.81, "lon": 46.60},
    "Al-Nargis (Res.)":    {"load": 0.25, "ev_density": 0.20, "lat": 24.84, "lon": 46.66},
    "Diplomatic Quarter":  {"load": 0.15, "ev_density": 0.10, "lat": 24.68, "lon": 46.62},
}

# ---------------------------------------------------------
# 3. إدارة الحالة (Session State)
# ---------------------------------------------------------
if 'industrial_load' not in st.session_state: st.session_state.industrial_load = 4.45 
if 'global_grid_cap' not in st.session_state: st.session_state.global_grid_cap = 18.0 
if 'base_residential_load' not in st.session_state: st.session_state.base_residential_load = 14.3
if 'sell_price' not in st.session_state: st.session_state.sell_price = 0.80
if 'buy_price' not in st.session_state: st.session_state.buy_price = 0.18
if 'dispatch_active' not in st.session_state: st.session_state.dispatch_active = False

if 'zones_data' not in st.session_state:
    st.session_state.zones_data = {
        z: {"status": "STABLE", "payout": 0, "dispatched_mw": 0, "local_deficit": 0} 
        for z in ZONE_WEIGHTS.keys()
    }

# ---------------------------------------------------------
# 4. المحرك الفيزيائي (Physics Engine)
# ---------------------------------------------------------
def calculate_grid_physics(pct_charging, pct_v2g):
    total_fleet = 100000
    
    # 1. حمل الشحن
    num_charging = int(total_fleet * (pct_charging / 100))
    ev_load_total_kw = num_charging * 7.0 * CHARGING_CONCURRENCY_FACTOR 
    ev_load_gw = ev_load_total_kw / 1e6 
    
    # 2. الأحمال الكلية
    total_res_load = st.session_state.base_residential_load + ev_load_gw
    total_city_load = total_res_load + st.session_state.industrial_load
    
    # 3. العجز الخام
    grid_cap = st.session_state.global_grid_cap
    raw_deficit = max(0, total_city_load - grid_cap)
    
    # 4. قدرة VPP الكلية (Max Potential)
    num_v2g = int(total_fleet * (pct_v2g / 100))
    # الحساب الدقيق: (عدد السيارات * قدرة الشاحن * الكفاءة) / 1000 = ميجاواط
    vpp_cap_mw = (num_v2g * AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000.0 
    
    return total_city_load, total_res_load, raw_deficit, vpp_cap_mw, num_charging, num_v2g

# ---------------------------------------------------------
# 5. دالة عرض الحي (Local View)
# ---------------------------------------------------------
def render_local_view(zone_name):
    pct_charging = st.session_state.get('pct_charging', 20)
    pct_v2g = st.session_state.get('pct_v2g', 60)
    
    _, total_res_load, raw_grid_deficit, _, _, _ = calculate_grid_physics(pct_charging, pct_v2g)
    
    params = ZONE_WEIGHTS[zone_name]
    total_fleet_riyadh = 100000
    
    # حساب الأحمال المحلية
    local_load_gw = total_res_load * params["load"]
    local_cap_gw = st.session_state.global_grid_cap * 0.8 * params["load"] 
    local_deficit_gw = max(0, local_load_gw - local_cap_gw)
    
    # V2G المحلية
    local_v2g_cars = int(total_fleet_riyadh * params["ev_density"] * (pct_v2g/100))
    available_vpp_mw = (local_v2g_cars * AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000.0
    
    st.title(f"📍 {zone_name} | Substation Control")
    
    # حالة الشبكة العامة
    current_total_dispatched = sum([d['dispatched_mw'] for z, d in st.session_state.zones_data.items()])
    net_deficit = max(0, raw_grid_deficit - (current_total_dispatched/1000))

    if net_deficit > 0.005:
         st.error(f"🚨 NATIONAL GRID ALERT: Remaining Deficit {net_deficit:.3f} GW. Support Needed!")
    elif raw_grid_deficit > 0:
         st.success(f"✅ GRID STABILIZED: VPP contribution active.")
    else:
         st.info("ℹ️ Grid Status: Nominal.")

    st.markdown("---")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Local Load", f"{local_load_gw:.3f} GW")
    
    if local_deficit_gw > 0:
        c2.metric("Local Deficit", f"{local_deficit_gw:.3f} GW", "CRITICAL", delta_color="inverse")
    else:
        c2.metric("Local Deficit", "0.000 GW", "Stable")
        
    c3.metric("Available V2G", f"{available_vpp_mw:.1f} MW", f"{local_v2g_cars} Cars")
    
    is_dispatched = st.session_state.zones_data[zone_name]['dispatched_mw'] > 0
    status_text = "INJECTING" if is_dispatched else "STANDBY"
    status_color = "#00C853" if is_dispatched else "#9E9E9E"
    
    c4.markdown(f"""<div class="kpi-card" style="border-left: 5px solid {status_color};">
        <div style="font-size: 12px; color: #555;">STATUS</div>
        <div style="color: {status_color}; font-size: 24px; font-weight: bold;">{status_text}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    
    # نضخ فقط ما هو مسموح به (سقف المحول)
    target_dispatch = min(available_vpp_mw, GRID_VOLTAGE_LIMIT_MW)
    
    c_btn, c_rest = st.columns([1, 2])
    with c_btn:
        if not is_dispatched:
            if st.button(f"⚡ INJECT {target_dispatch:.0f} MW"):
                with st.spinner("Syncing Inverters..."):
                    time.sleep(0.5)
                    st.session_state.zones_data[zone_name]['dispatched_mw'] = target_dispatch
                    st.session_state.zones_data[zone_name]['payout'] = target_dispatch * 1000 * st.session_state.sell_price * 4
                    st.session_state.zones_data[zone_name]['status'] = "STABILIZED"
                    st.rerun()
        else:
            if st.button("🔴 STOP INJECTION"):
                st.session_state.zones_data[zone_name]['dispatched_mw'] = 0
                st.session_state.zones_data[zone_name]['payout'] = 0
                st.session_state.zones_data[zone_name]['status'] = "STABLE"
                st.rerun()
                
    lt1, lt2 = st.tabs(["🛡️ Infrastructure Health", "💰 Local Financials"])
    
    with lt1:
        st.subheader("Asset Health Monitoring")
        g1, g2 = st.columns(2)
        load_pct_weak = 95 if (not is_dispatched and local_deficit_gw > 0) else 40
        fig_w = go.Figure(go.Indicator(mode="gauge+number", value=load_pct_weak, title={'text': "Weak Transformers (Load %)"}, 
                                     gauge={'axis': {'range': [0, 120]}, 'bar': {'color': "red" if load_pct_weak > 90 else "#FFA500"}}))
        fig_w.update_layout(paper_bgcolor="white", font={'color': "black"}, height=250)
        g1.plotly_chart(fig_w, use_container_width=True)

        load_pct_strong = 60
        if is_dispatched: load_pct_strong = 75
        fig_s = go.Figure(go.Indicator(mode="gauge+number", value=load_pct_strong, title={'text': "Modern Substations (Load %)"}, 
                                     gauge={'axis': {'range': [0, 120]}, 'bar': {'color': "#00C853"}}))
        fig_s.update_layout(paper_bgcolor="white", font={'color': "black"}, height=250)
        g2.plotly_chart(fig_s, use_container_width=True)

    with lt2:
        if is_dispatched:
            f1, f2 = st.columns(2)
            f1.metric("Revenue (4h Cycle)", f"{st.session_state.zones_data[zone_name]['payout']:,.0f} SAR")
            f2.metric("Power Exported", f"{st.session_state.zones_data[zone_name]['dispatched_mw']:.1f} MW")
        else:
            st.info("No active settlement in this zone.")

# ---------------------------------------------------------
# 6. الواجهة الرئيسية والتحكم (Main Dashboard)
# ---------------------------------------------------------
with st.sidebar:
    st.title("🏙️ Scope Selection")
    options = ["Riyadh City Overview"] + list(ZONE_WEIGHTS.keys())
    selected_zone = st.selectbox("Select View", options)
    
    st.markdown("---")
    st.header("⚙️ Simulation Params")
    
    st.session_state.industrial_load = st.slider("Ind. Load (GW)", 2.0, 8.0, 4.45) # تم ضبطه ليعطي عجزاً مبدئياً
    st.session_state.sell_price = st.slider("Sell Price (SAR/kWh)", 0.1, 2.0, 0.80)
    st.session_state.buy_price = st.slider("Buy Price (SAR/kWh)", 0.05, 1.0, 0.18)
    
    pct_charging = st.slider("Charging %", 0, 50, 20)
    pct_v2g = st.slider("V2G Ready %", 0, 80, 60)
    
    st.session_state.pct_charging = pct_charging
    st.session_state.pct_v2g = pct_v2g

    st.markdown("---")
    st.markdown("### 👨‍💻 Developed By")
    st.markdown("**Eng. Mohamed Alwedaa**")
    
    linkedin_url = "https://www.linkedin.com/in/" 
    st.markdown(f"""
    <a href="{linkedin_url}" target="_blank" style="text-decoration: none;">
        <button style="background-color: #0077b5; color: white; border: none; padding: 8px; border-radius: 5px; width: 100%; cursor: pointer;">
            Connect on LinkedIn
        </button>
    </a>
    """, unsafe_allow_html=True)

if selected_zone != "Riyadh City Overview":
    render_local_view(selected_zone)
else:
    # --- [Dashboard] العرض الرئيسي لمدينة الرياض ---
    st.title("🇸🇦 Riyadh City | VPP Strategic Analytics")
    
    # 1. الحسابات الفيزيائية
    total_city_load, total_res_load, raw_deficit, vpp_cap_mw, num_charging, num_v2g = calculate_grid_physics(pct_charging, pct_v2g)
    
    # 2. حساب الضخ الفعلي (Active Dispatch)
    # نجمع ما يتم ضخه من الأحياء حالياً
    manual_dispatch_sum = sum([d['dispatched_mw'] for z, d in st.session_state.zones_data.items()])
    
    # إذا كان التحكم المركزي مفعلاً، نستخدمه
    if st.session_state.dispatch_active:
        total_dispatched_mw = manual_dispatch_sum
    else:
        total_dispatched_mw = manual_dispatch_sum

    # 3. حساب العجز الصافي بعد التدخل
    net_deficit_gw = max(0, raw_deficit - (total_dispatched_mw/1000.0))

    # --- مؤشرات الأداء (KPIs) ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Load", f"{total_city_load:.2f} GW")
    
    # [تصحيح] حساب السعة المتبقية (Unused VPP Cap)
    # السعة المتبقية = السعة الكلية المتاحة - السعة المستخدمة حالياً
    remaining_vpp_mw = max(0, vpp_cap_mw - total_dispatched_mw)
    
    # [تصحيح] حساب عدد السيارات المتبقية (تقريبي بناءً على الطاقة المتبقية)
    one_car_mw = (AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000.0
    remaining_cars = int(remaining_vpp_mw / one_car_mw) if one_car_mw > 0 else 0
    
    k2.metric(
        "Unused VPP Cap", 
        f"{remaining_vpp_mw:.0f} MW", 
        f"{remaining_cars:,} Cars Idle", # عرض السيارات المتبقية بدلاً من المستخدمة
        delta_color="off"
    )
    
    # حالة العجز
    if raw_deficit > 0:
        # إذا تم تغطية العجز بالكامل (أو بقي شيء لا يذكر)
        if net_deficit_gw < 0.05 and total_dispatched_mw > 0:
            k3.metric("Grid Deficit", "STABILIZED ✅", f"Raw was: {raw_deficit:.2f} GW")
        else:
            k3.metric("Grid Deficit", f"{net_deficit_gw:.3f} GW", "CRITICAL ⚠️", delta_color="inverse")
    else:
        k3.metric("Grid Deficit", "Surplus", "Stable")
        
    k4.metric("EV Load", f"+{num_charging*7/1000:.1f} MW", f"{num_charging:,} Cars")

    st.markdown("---")

    # لوحة التحكم المركزي
    col_map_ctrl, col_act_ctrl = st.columns([3, 1])
    with col_act_ctrl:
        st.markdown("#### Central Dispatch")
        
        if st.session_state.dispatch_active:
            btn_txt = "🔴 SCRAM (STOP ALL)"
        else:
            btn_txt = "⚡ ACTIVATE ALL VPPs"

        # الزر يظهر فقط إذا كان هناك عجز يحتاج تدخل
        if raw_deficit > 0 or st.session_state.dispatch_active:
            if st.button(btn_txt):
                st.session_state.dispatch_active = not st.session_state.dispatch_active
                
                if st.session_state.dispatch_active:
                    # تفعيل كل الأحياء
                    for z, params in ZONE_WEIGHTS.items():
                        local_fleet = 100000 * params['ev_density']
                        # حساب القدرة المتاحة للحي
                        local_mw_available = (local_fleet * (pct_v2g/100) * AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000
                        # تحديد الهدف: إما سعة الحي القصوى أو سقف الشبكة
                        target = min(local_mw_available, GRID_VOLTAGE_LIMIT_MW)
                        
                        st.session_state.zones_data[z]['dispatched_mw'] = target
                        st.session_state.zones_data[z]['payout'] = target * 1000 * st.session_state.sell_price * 4
                        st.session_state.zones_data[z]['status'] = "STABILIZED"
                else:
                    # إيقاف كل الأحياء
                    for z in st.session_state.zones_data:
                        st.session_state.zones_data[z]['dispatched_mw'] = 0
                        st.session_state.zones_data[z]['payout'] = 0
                        st.session_state.zones_data[z]['status'] = "STABLE"
                
                st.rerun()
        else:
            st.info("Grid Stable. No Central Action Needed.")

    # الخرائط والرسوم البيانية
    map_data = []
    for zone, params in ZONE_WEIGHTS.items():
        status = "STABLE"
        color = "#00C853"
        if net_deficit_gw > 0:
            status = "CRITICAL"
            color = "#D32F2F"
        elif st.session_state.dispatch_active or st.session_state.zones_data[zone]['dispatched_mw'] > 0:
            status = "INJECTING"
            color = "#2962FF"
            
        map_data.append({
            "Zone": zone, "lat": params['lat'], "lon": params['lon'], 
            "Status": status, "Color": color, "Load": total_res_load * params['load']
        })
    
    df_map = pd.DataFrame(map_data)
    
    c_map1, c_map2 = st.columns([2, 1])
    with c_map1:
        st.subheader("🗺️ Live Grid Control Map")
        fig_map = px.scatter_mapbox(df_map, lat="lat", lon="lon", color="Status", size="Load",
                                    color_discrete_map={"INJECTING": "#2962FF", "CRITICAL": "#D32F2F", "STABLE": "#00C853"},
                                    zoom=10, mapbox_style="carto-positron", height=450, size_max=40)
        fig_map.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, paper_bgcolor="white", font=dict(color="black"))
        st.plotly_chart(fig_map, use_container_width=True)
    
    with c_map2:
        st.subheader("📊 Fleet Distribution")
        np.random.seed(99)
        fleet_map_df = pd.DataFrame({
            'lat': np.random.normal(24.71, 0.08, 1000),
            'lon': np.random.normal(46.67, 0.08, 1000),
            'Status': np.random.choice(['Charging', 'V2G Ready', 'Idle'], 1000, p=[pct_charging/100, pct_v2g/100, (100-pct_charging-pct_v2g)/100])
        })
        color_map_fleet = {'Charging': '#D32F2F', 'V2G Ready': '#00C853', 'Idle': '#999999'}
        fig_fleet = px.scatter_mapbox(fleet_map_df, lat="lat", lon="lon", color="Status", color_discrete_map=color_map_fleet, 
                                      zoom=9.5, mapbox_style="carto-positron", height=450)
        fig_fleet.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, paper_bgcolor="white", font=dict(color="black"), showlegend=False)
        st.plotly_chart(fig_fleet, use_container_width=True)

    # التبويبات الثلاثة
    t1, t2, t3 = st.tabs(["📈 Load Curve Analysis", "🔌 Charging Profile", "📋 Operations Settlement"])
    
    with t1:
        hours = list(range(24))
        base_curve = []
        for h in hours:
            if 0 <= h < 6:   factor = 0.55 
            elif 6 <= h < 11: factor = 0.75 
            elif 11 <= h < 15: factor = 0.65 
            elif 15 <= h < 19: factor = 0.98 
            elif 19 <= h < 23: factor = 0.85 
            else: factor = 0.60
            base_curve.append(total_city_load * (factor + np.random.normal(0, 0.01)))

        opt_curve = []
        dispatch_gw = total_dispatched_mw / 1000.0
        
        for h, val in enumerate(base_curve):
            if 15 <= h <= 18 and dispatch_gw > 0:
                opt_curve.append(max(0, val - dispatch_gw))
            else:
                opt_curve.append(val)

        fig_l = go.Figure()
        fig_l.add_vrect(x0=15, x1=18, fillcolor="red", opacity=0.1, annotation_text="Peak Zone", annotation_position="top left")
        fig_l.add_trace(go.Scatter(x=hours, y=base_curve, name='BAU Load', line=dict(color='#D32F2F', width=2, dash='dot')))
        fig_l.add_trace(go.Scatter(x=hours, y=opt_curve, name='Optimized (V2G)', fill='tozeroy', line=dict(color='#00C853', width=3)))
        fig_l.update_layout(
            template="plotly_white", height=350, 
            paper_bgcolor="white", margin=dict(l=0,r=0,t=10,b=0), 
            font=dict(color="black"), 
            xaxis_title="Hour", yaxis_title="GW",
            xaxis=dict(title_font=dict(color="black"), tickfont=dict(color="black")),
            yaxis=dict(title_font=dict(color="black"), tickfont=dict(color="black")),
            legend=dict(font=dict(color="black"))
        )
        st.plotly_chart(fig_l, use_container_width=True)

    with t2:
        hours = list(range(24))
        prices = [st.session_state.sell_price if 13 <= h <= 17 else st.session_state.buy_price for h in hours]
        charging_profile = [vpp_cap_mw * 0.1] * 24
        for h in range(7): charging_profile[h] = vpp_cap_mw * 0.8
        
        fig_sc = go.Figure()
        fig_sc.add_trace(go.Bar(x=hours, y=charging_profile, name='Fleet Load (MW)', marker_color='#00C853', yaxis='y'))
        fig_sc.add_trace(go.Scatter(x=hours, y=prices, name='Tariff (SAR)', line=dict(color='#D32F2F', width=3, dash='dot'), yaxis='y2'))
        
        fig_sc.update_layout(
            template="plotly_white", paper_bgcolor="white", height=350, 
            font=dict(color="black"),
            yaxis=dict(title="MW", tickfont=dict(color="#00C853"), title_font=dict(color="#00C853")),
            yaxis2=dict(title="SAR", tickfont=dict(color="#D32F2F"), title_font=dict(color="#D32F2F"), overlaying="y", side="right"),
            legend=dict(x=0, y=1.1, orientation="h", font=dict(color="black"))
        )
        st.plotly_chart(fig_sc, use_container_width=True)

    with t3:
        st.subheader("📊 Zone Operations & Settlement Report")
        
        table_data = []
        total_active_cars = 0
        total_payout = 0
        total_mw_table = 0
        
        for zone, params in ZONE_WEIGHTS.items():
            state_data = st.session_state.zones_data[zone]
            z_mw = state_data['dispatched_mw']
            z_payout = state_data['payout']
            
            if z_mw > 0:
                if st.session_state.dispatch_active:
                    status = "🟢 Active (Central)"
                else:
                    status = "🟢 Active (Local)"
                
                # حساب السيارات المشاركة
                one_car_capacity_mw = (AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000
                z_cars = int(z_mw / one_car_capacity_mw)
            else:
                status = "⚪ Standby"
                z_cars = 0

            table_data.append({
                "Zone (District)": zone,
                "Status": status,
                "Active V2G Cars": f"{z_cars:,}",
                "Dispatched Power (MW)": f"{z_mw:.2f}",
                "Est. Payout (SAR)": f"{z_payout:,.0f}"
            })
            
            total_active_cars += z_cars
            total_mw_table += z_mw
            total_payout += z_payout

        df_ops = pd.DataFrame(table_data)
        st.dataframe(
            df_ops, 
            use_container_width=True, 
            column_config={
                "Status": st.column_config.TextColumn("System Status"),
                "Est. Payout (SAR)": st.column_config.TextColumn("Payment Due (SAR)"),
            }
        )
        
        st.markdown("---")
        c_tot1, c_tot2, c_tot3 = st.columns(3)
        c_tot1.metric("Total Participating Cars", f"{total_active_cars:,}")
        c_tot2.metric("Total Power Dispatched", f"{total_mw_table:.2f} MW")
        c_tot3.metric("Total Settlement Amount", f"{total_payout:,.0f} SAR", "4 Hours Cycle")
