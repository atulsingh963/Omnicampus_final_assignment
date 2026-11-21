"""
End-to-End Analysis, Modeling, and Financial Simulation
GCI Final Assignment - Company A Telecom Churn Prevention
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    roc_auc_score,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    roc_curve
)
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

import xgboost as xgb
import lightgbm as lgb

# Set style
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
plt.rcParams['font.size'] = 11
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['figure.titlesize'] = 16

IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'images')
os.makedirs(IMAGES_DIR, exist_ok=True)

def find_data_paths():
    base_dirs = [
        os.path.join(os.path.dirname(__file__), '..', 'details'),
        os.path.join(os.path.dirname(__file__), 'details'),
        os.path.join(os.path.dirname(__file__), 'telecom'),
        os.path.join(os.getcwd(), 'details'),
        os.path.join(os.getcwd(), 'telecom'),
        os.getcwd()
    ]
    for b in base_dirs:
        c_path = os.path.join(b, 'Client.csv')
        r_path = os.path.join(b, 'Record.csv')
        if os.path.exists(c_path) and os.path.exists(r_path):
            return c_path, r_path
    raise FileNotFoundError("Could not find Client.csv and Record.csv in standard paths.")

def load_and_preprocess_data():
    client_path, record_path = find_data_paths()
    print(f"Loading data from:\n  {client_path}\n  {record_path}")
    client = pd.read_csv(client_path)
    record = pd.read_csv(record_path)
    
    # 1:1 join
    df = record.merge(client, on='Customer_ID', how='inner')
    print(f"Merged Dataset Shape: {df.shape}")
    
    # Drop Customer_ID
    customer_ids = df['Customer_ID']
    df = df.drop(columns=['Customer_ID'])
    
    # Feature Engineering
    print("Performing feature engineering...")
    # 1. Behavioral usage drop flag (MOU decreased significantly)
    df['mou_drop_ratio'] = df['change_mou'].apply(lambda x: 1 if x < -20 else 0)
    # 2. Revenue drop flag
    df['rev_drop_ratio'] = df['change_rev'].apply(lambda x: 1 if x < -10 else 0)
    # 3. Bill shock: has overage charges
    df['bill_shock_flag'] = ((df['ovrmou_Mean'] > 0) & (df['ovrrev_Mean'] > 5)).astype(int)
    # 4. Equipment lifecycle cliff: phone older than 1 year (365 days)
    df['eqp_old_flag'] = (df['eqpdays'] >= 365).astype(int)
    # 5. Service friction ratio: dropped calls to attempted calls
    df['call_failure_rate'] = df['drop_blk_Mean'] / (df['attempt_Mean'] + 1.0)
    # 6. Customer care intensity
    df['care_call_ratio'] = df['custcare_Mean'] / (df['complete_Mean'] + 1.0)
    # 7. Recurring revenue proportion
    df['mrc_to_rev_ratio'] = df['totmrc_Mean'] / (df['rev_Mean'].clip(lower=1.0))
    # 8. Outbound vs Inbound ratio
    df['outbound_ratio'] = df['plcd_vce_Mean'] / (df['recv_vce_Mean'] + 1.0)
    
    return df, customer_ids

def generate_eda_figures(df):
    print("Generating EDA visualizations...")
    
    # FIG 1: Churn Distribution & Regional/Demographic Overview
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    
    # 1.1 Churn Target Balance
    churn_counts = df['churn'].value_counts()
    axes[0].pie(
        churn_counts,
        labels=['Non-Churn (0)\n50,438 (50.4%)', 'Churn (1)\n49,562 (49.6%)'],
        autopct='%1.1f%%',
        colors=['#2b5c8f', '#d9534f'],
        startangle=140,
        wedgeprops={'edgecolor': 'white', 'linewidth': 2}
    )
    axes[0].set_title('Target Distribution: Churn vs Non-Churn', fontweight='bold')
    
    # 1.2 Churn Rate by Equipment Age Bracket
    df_temp = df.copy()
    df_temp['eqp_bracket'] = pd.cut(
        df_temp['eqpdays'],
        bins=[-np.inf, 180, 365, 540, 730, np.inf],
        labels=['<6 Mo', '6-12 Mo', '12-18 Mo', '18-24 Mo', '>24 Mo']
    )
    eqp_churn = df_temp.groupby('eqp_bracket', observed=False)['churn'].mean() * 100
    bars = axes[1].bar(eqp_churn.index, eqp_churn.values, color='#337ab7', edgecolor='black', alpha=0.85)
    axes[1].axhline(49.56, color='red', linestyle='--', linewidth=1.5, label='Avg Churn (49.6%)')
    axes[1].set_title('Churn Rate by Equipment Age Bracket', fontweight='bold')
    axes[1].set_ylabel('Churn Rate (%)')
    axes[1].set_ylim(35, 65)
    axes[1].legend(loc='upper left')
    for bar in bars:
        h = bar.get_height()
        axes[1].text(bar.get_x() + bar.get_width()/2., h + 0.8, f'{h:.1f}%', ha='center', va='bottom', fontweight='bold')
        
    # 1.3 Refurbished vs New Handset
    refurb_churn = df.groupby('refurb_new')['churn'].mean() * 100
    colors_refurb = ['#5cb85c' if idx == 'N' else '#f0ad4e' for idx in refurb_churn.index]
    bars2 = axes[2].bar(['New Handset (N)', 'Refurbished (R)'], refurb_churn.values, color=colors_refurb, edgecolor='black', alpha=0.85)
    axes[2].axhline(49.56, color='red', linestyle='--', linewidth=1.5, label='Avg Churn (49.6%)')
    axes[2].set_title('Churn Rate: New vs Refurbished Handset', fontweight='bold')
    axes[2].set_ylabel('Churn Rate (%)')
    axes[2].set_ylim(40, 60)
    axes[2].legend(loc='upper left')
    for bar in bars2:
        h = bar.get_height()
        axes[2].text(bar.get_x() + bar.get_width()/2., h + 0.6, f'{h:.1f}%', ha='center', va='bottom', fontweight='bold')
        
    plt.tight_layout()
    fig1_path = os.path.join(IMAGES_DIR, 'fig1_churn_overview.png')
    plt.savefig(fig1_path, dpi=300)
    plt.close()
    print(f"Saved: {fig1_path}")
    
    # FIG 2: The Three Smoking Guns (Equipment Age, Usage Velocity, Bill Shock)
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    
    # 2.1 Equipment Age Distribution by Churn
    sns.kdeplot(data=df, x='eqpdays', hue='churn', common_norm=False, palette=['#2b5c8f', '#d9534f'], fill=True, alpha=0.4, ax=axes[0])
    axes[0].axvline(365, color='black', linestyle=':', linewidth=2, label='1-Year Contract Cliff (365d)')
    axes[0].set_title('Equipment Age Distribution (eqpdays)', fontweight='bold')
    axes[0].set_xlabel('Equipment Age (Days)')
    axes[0].set_xlim(0, 1200)
    axes[0].legend(['Churn (1)', 'Non-Churn (0)', '1-Year Mark'], loc='upper right')
    
    # 2.2 Change in MOU by Churn
    df_temp['mou_drop_group'] = pd.cut(
        df_temp['change_mou'],
        bins=[-np.inf, -50, -20, 0, 20, np.inf],
        labels=['Severe (<-50%)', 'Moderate (-50 to -20%)', 'Slight Drop (-20 to 0%)', 'Slight Rise (0-20%)', 'Surge (>20%)']
    )
    mou_churn = df_temp.groupby('mou_drop_group', observed=False)['churn'].mean() * 100
    bars_mou = axes[1].bar(mou_churn.index, mou_churn.values, color='#e67e22', edgecolor='black', alpha=0.85)
    axes[1].axhline(49.56, color='red', linestyle='--', linewidth=1.5, label='Avg Churn')
    axes[1].set_title('Churn Rate vs Monthly Usage Velocity (change_mou)', fontweight='bold')
    axes[1].set_ylabel('Churn Rate (%)')
    axes[1].set_ylim(40, 60)
    axes[1].tick_params(axis='x', rotation=25)
    axes[1].legend(loc='upper right')
    for bar in bars_mou:
        h = bar.get_height()
        axes[1].text(bar.get_x() + bar.get_width()/2., h + 0.5, f'{h:.1f}%', ha='center', va='bottom', fontweight='bold', fontsize=9)

    # 2.3 Overage Charges & Bill Shock
    df_temp['ovr_bucket'] = pd.cut(
        df_temp['ovrrev_Mean'],
        bins=[-np.inf, 0, 5, 20, 50, np.inf],
        labels=['No Overage ($0)', 'Low ($0-$5)', 'Mid ($5-$20)', 'High ($20-$50)', 'Severe (>$50)']
    )
    ovr_churn = df_temp.groupby('ovr_bucket', observed=False)['churn'].mean() * 100
    bars_ovr = axes[2].bar(ovr_churn.index, ovr_churn.values, color='#9b59b6', edgecolor='black', alpha=0.85)
    axes[2].axhline(49.56, color='red', linestyle='--', linewidth=1.5, label='Avg Churn')
    axes[2].set_title('Bill Shock: Churn Rate by Overage Revenue', fontweight='bold')
    axes[2].set_ylabel('Churn Rate (%)')
    axes[2].set_ylim(45, 55)
    axes[2].tick_params(axis='x', rotation=25)
    axes[2].legend(loc='upper right')
    for bar in bars_ovr:
        h = bar.get_height()
        axes[2].text(bar.get_x() + bar.get_width()/2., h + 0.3, f'{h:.1f}%', ha='center', va='bottom', fontweight='bold', fontsize=9)

    plt.tight_layout()
    fig2_path = os.path.join(IMAGES_DIR, 'fig2_behavioral_signals.png')
    plt.savefig(fig2_path, dpi=300)
    plt.close()
    print(f"Saved: {fig2_path}")

def train_and_evaluate_models(df):
    print("Preparing training data and benchmarking models...")
    
    y = df['churn']
    X = df.drop(columns=['churn'])
    
    # Identify categorical and numerical columns
    cat_cols = X.select_dtypes(include=['object', 'category']).columns.tolist()
    num_cols = X.select_dtypes(include=[np.number]).columns.tolist()
    
    print(f"Features: Total={X.shape[1]}, Numeric={len(num_cols)}, Categorical={len(cat_cols)}")
    
    # For tree models, categorical encoding
    X_encoded = X.copy()
    for col in cat_cols:
        X_encoded[col] = X_encoded[col].astype('category')
        
    X_train, X_test, y_train, y_test = train_test_split(
        X_encoded, y, test_size=0.25, random_state=42, stratify=y
    )
    
    # 1. Logistic Regression Baseline (numeric features imputed & scaled)
    print("Training 1/4: Logistic Regression...")
    imputer = SimpleImputer(strategy='median')
    scaler = StandardScaler()
    
    X_train_num = scaler.fit_transform(imputer.fit_transform(X_train[num_cols]))
    X_test_num = scaler.transform(imputer.transform(X_test[num_cols]))
    
    lr = LogisticRegression(max_iter=1000, random_state=42, solver='lbfgs')
    lr.fit(X_train_num, y_train)
    lr_probs = lr.predict_proba(X_test_num)[:, 1]
    lr_preds = (lr_probs >= 0.5).astype(int)
    
    # 2. Random Forest Classifier
    print("Training 2/4: Random Forest...")
    rf_imputer = SimpleImputer(strategy='median')
    X_train_rf = rf_imputer.fit_transform(X_train[num_cols])
    X_test_rf = rf_imputer.transform(X_test[num_cols])
    
    rf = RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_split=10, n_jobs=-1, random_state=42)
    rf.fit(X_train_rf, y_train)
    rf_probs = rf.predict_proba(X_test_rf)[:, 1]
    rf_preds = (rf_probs >= 0.5).astype(int)
    
    # 3. XGBoost Classifier
    print("Training 3/4: XGBoost...")
    # One-hot / frequency encode categoricals for XGBoost
    X_train_xgb = pd.get_dummies(X_train, columns=cat_cols, drop_first=True)
    X_test_xgb = pd.get_dummies(X_test, columns=cat_cols, drop_first=True)
    X_train_xgb, X_test_xgb = X_train_xgb.align(X_test_xgb, join='left', axis=1, fill_value=0)
    
    xgb_model = xgb.XGBClassifier(
        n_estimators=250,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric='logloss',
        random_state=42,
        n_jobs=-1
    )
    xgb_model.fit(X_train_xgb, y_train)
    xgb_probs = xgb_model.predict_proba(X_test_xgb)[:, 1]
    xgb_preds = (xgb_probs >= 0.5).astype(int)
    
    # 4. LightGBM Classifier (handles categoricals natively)
    print("Training 4/4: LightGBM...")
    lgb_model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.04,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
        n_jobs=-1
    )
    lgb_model.fit(X_train, y_train)
    lgb_probs = lgb_model.predict_proba(X_test)[:, 1]
    lgb_preds = (lgb_probs >= 0.5).astype(int)
    
    # Compile Metrics Table
    models_dict = {
        'Logistic Regression': (lr_preds, lr_probs),
        'Random Forest': (rf_preds, rf_probs),
        'XGBoost': (xgb_preds, xgb_probs),
        'LightGBM': (lgb_preds, lgb_probs)
    }
    
    metrics_summary = []
    for name, (preds, probs) in models_dict.items():
        metrics_summary.append({
            'Model': name,
            'ROC-AUC': float(roc_auc_score(y_test, probs)),
            'Accuracy': float(accuracy_score(y_test, preds)),
            'Precision': float(precision_score(y_test, preds)),
            'Recall': float(recall_score(y_test, preds)),
            'F1-Score': float(f1_score(y_test, preds))
        })
        
    metrics_df = pd.DataFrame(metrics_summary)
    print("\n=== Model Benchmark Results ===")
    print(metrics_df.to_string(index=False))
    
    # Save metrics to JSON
    with open(os.path.join(IMAGES_DIR, 'model_metrics.json'), 'w') as f:
        json.dump(metrics_summary, f, indent=4)
        
    # FIG 3: ROC Curves
    plt.figure(figsize=(9, 7))
    colors = {'Logistic Regression': '#7f8c8d', 'Random Forest': '#2980b9', 'XGBoost': '#27ae60', 'LightGBM': '#e74c3c'}
    styles = {'Logistic Regression': ':', 'Random Forest': '-.', 'XGBoost': '--', 'LightGBM': '-'}
    
    for name, (preds, probs) in models_dict.items():
        fpr, tpr, _ = roc_curve(y_test, probs)
        auc_val = roc_auc_score(y_test, probs)
        plt.plot(fpr, tpr, label=f"{name} (AUC = {auc_val:.3f})", color=colors[name], linestyle=styles[name], linewidth=2.2)
        
    plt.plot([0, 1], [0, 1], 'k--', alpha=0.5, label='Random Guess (AUC = 0.500)')
    plt.xlabel('False Positive Rate (1 - Specificity)')
    plt.ylabel('True Positive Rate (Sensitivity / Recall)')
    plt.title('Receiver Operating Characteristic (ROC) Curve Comparison', fontweight='bold')
    plt.legend(loc='lower right', frameon=True)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    fig3_path = os.path.join(IMAGES_DIR, 'fig3_model_comparison_roc.png')
    plt.savefig(fig3_path, dpi=300)
    plt.close()
    print(f"Saved: {fig3_path}")
    
    # FIG 4: Feature Importance (LightGBM) categorized by Intervenability
    importances = pd.Series(lgb_model.feature_importances_, index=X.columns).sort_values(ascending=False).head(15)
    
    # Intervenable vs Profiling classification
    intervenable_features = [
        'eqpdays', 'change_mou', 'change_rev', 'mou_Mean', 'totmrc_Mean',
        'hnd_price', 'drop_vce_Mean', 'drop_blk_Mean', 'mou_cvce_Mean',
        'bill_shock_flag', 'call_failure_rate', 'eqp_old_flag'
    ]
    bar_colors = ['#27ae60' if f in intervenable_features else '#2980b9' for f in importances.index]
    
    plt.figure(figsize=(11, 7))
    bars = plt.barh(importances.index[::-1], importances.values[::-1], color=bar_colors[::-1], edgecolor='black', alpha=0.85)
    plt.title('Top 15 Feature Importances (LightGBM) & Actionability', fontweight='bold')
    plt.xlabel('Feature Importance (Split Count in Decision Trees)')
    
    # Add custom legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#27ae60', edgecolor='black', label='Actionable / Intervenable Lever (Target of Business Proposal)'),
        Patch(facecolor='#2980b9', edgecolor='black', label='Contextual / Demographic Profiling Factor')
    ]
    plt.legend(handles=legend_elements, loc='lower right', frameon=True)
    plt.tight_layout()
    fig4_path = os.path.join(IMAGES_DIR, 'fig4_feature_importance.png')
    plt.savefig(fig4_path, dpi=300)
    plt.close()
    print(f"Saved: {fig4_path}")
    
    # FIG 5: Confusion Matrix for Best Model (LightGBM)
    cm = confusion_matrix(y_test, lgb_preds)
    plt.figure(figsize=(7, 6))
    sns.heatmap(
        cm,
        annot=True,
        fmt='d',
        cmap='Blues',
        xticklabels=['Predicted Active (0)', 'Predicted Churn (1)'],
        yticklabels=['Actual Active (0)', 'Actual Churn (1)'],
        cbar=False,
        annot_kws={'size': 14, 'weight': 'bold'}
    )
    plt.title(f'Confusion Matrix — LightGBM\nAccuracy: {accuracy_score(y_test, lgb_preds):.3f} | ROC-AUC: {roc_auc_score(y_test, lgb_probs):.3f}', fontweight='bold')
    plt.ylabel('Actual Label')
    plt.xlabel('Predicted Label')
    plt.tight_layout()
    fig5_path = os.path.join(IMAGES_DIR, 'fig5_confusion_matrix.png')
    plt.savefig(fig5_path, dpi=300)
    plt.close()
    print(f"Saved: {fig5_path}")
    
    return lgb_model, X_test, y_test, lgb_probs

def run_financial_simulation(y_test, probs, test_indices, df):
    print("Running Profit Maximization System (PMS) and business ROI simulation...")
    
    # Simulation Parameters (Standard Telecom Benchmarks from Bain & Co & Company A)
    # Total customer base: 100,000 subscribers
    # Average monthly revenue (avgrev): ~$58/mo -> $696 annual customer value
    # Baseline annual churn: ~49.6% -> ~49,560 subscribers churn/year
    # Total annual revenue at risk = 49,560 * $696 = $34,493,760 (~$34.5 Million)
    
    # Retention Campaign Economics:
    # Cost per targeted intervention offer C_offer = $50 (handset upgrade credit or discounted plan voucher)
    # Intervention success rate (fraction of at-risk users who accept and stay for 1 year) = 28%
    # Customer Annual Lifetime Value preserved V_saved = $696
    
    # Evaluate net profit across decision thresholds from 0.1 to 0.9
    thresholds = np.linspace(0.1, 0.9, 81)
    profits = []
    retained_counts = []
    targeted_counts = []
    saved_revenues = []
    campaign_costs = []
    
    # Scale from test set (25,000) to full population (100,000) by 4x multiplier
    scale_factor = 100000.0 / len(y_test)
    
    for t in thresholds:
        targeted_mask = (probs >= t)
        n_targeted = targeted_mask.sum() * scale_factor
        
        # True churners correctly identified (True Positives)
        n_true_churners_targeted = ((probs >= t) & (y_test == 1)).sum() * scale_factor
        
        # Customers successfully retained by the campaign
        n_retained = n_true_churners_targeted * 0.28
        
        gross_rev_saved = n_retained * 696.0
        total_offer_cost = n_targeted * 50.0
        
        # Fixed platform / system cost amortization: $200,000/yr
        fixed_cost = 200000.0
        
        net_profit = gross_rev_saved - total_offer_cost - fixed_cost
        
        profits.append(net_profit)
        retained_counts.append(n_retained)
        targeted_counts.append(n_targeted)
        saved_revenues.append(gross_rev_saved)
        campaign_costs.append(total_offer_cost)
        
    profits = np.array(profits)
    opt_idx = np.argmax(profits)
    opt_threshold = thresholds[opt_idx]
    max_net_profit = profits[opt_idx]
    opt_targeted = targeted_counts[opt_idx]
    opt_retained = retained_counts[opt_idx]
    opt_rev_saved = saved_revenues[opt_idx]
    opt_cost = campaign_costs[opt_idx]
    opt_roi = (max_net_profit / (opt_cost + 200000.0)) * 100
    
    print(f"\n=== Financial Optimization Results (PMS) ===")
    print(f"Optimal Probability Threshold: {opt_threshold:.2f}")
    print(f"Targeted Population Size: {opt_targeted:,.0f} subscribers ({opt_targeted/100000*100:.1f}% of base)")
    print(f"Subscribers Successfully Retained: {opt_retained:,.0f} accounts")
    print(f"Gross Revenue Preserved: ${opt_rev_saved:,.2f}")
    print(f"Campaign Offer Cost: ${opt_cost:,.2f}")
    print(f"Platform Amortization: $200,000.00")
    print(f"Maximum Net Profit Lift: ${max_net_profit:,.2f}")
    print(f"Campaign Net ROI: {opt_roi:.1f}%")
    
    # FIG 6: Profit Maximization Curve (PMS)
    fig, ax1 = plt.subplots(figsize=(10, 6.5))
    
    # Net Profit curve
    color1 = '#27ae60'
    ax1.plot(thresholds, profits / 1e6, color=color1, linewidth=3, label='Net Annual Profit Lift ($M)')
    ax1.axvline(opt_threshold, color='#e74c3c', linestyle='--', linewidth=2, label=f'Optimal Cutoff: {opt_threshold:.2f}')
    ax1.scatter([opt_threshold], [max_net_profit / 1e6], color='#e74c3c', s=120, zorder=5)
    ax1.set_xlabel('Model Churn Probability Decision Threshold', fontweight='bold')
    ax1.set_ylabel('Net Annual Profit Lift (Million USD)', color=color1, fontweight='bold')
    ax1.tick_params(axis='y', labelcolor=color1)
    ax1.set_ylim(-0.5, 3.0)
    
    # Secondary axis: Targeted Subscribers
    ax2 = ax1.twinx()
    color2 = '#2980b9'
    ax2.plot(thresholds, np.array(targeted_counts) / 1000, color=color2, linestyle='-.', linewidth=2, label='Targeted Accounts (Thousands)')
    ax2.set_ylabel('Targeted Accounts (Thousands)', color=color2, fontweight='bold')
    ax2.tick_params(axis='y', labelcolor=color2)
    
    # Annotate optimum
    ax1.annotate(
        f'Peak Net Profit: +${max_net_profit/1e6:.2f}M\nTargeting {opt_targeted:,.0f} accounts\nROI: {opt_roi:.0f}%',
        xy=(opt_threshold, max_net_profit / 1e6),
        xytext=(opt_threshold + 0.1, (max_net_profit / 1e6) - 0.4),
        arrowprops=dict(facecolor='black', arrowstyle='->', lw=1.5),
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#f9f9f9', edgecolor='#e74c3c', lw=1.5),
        fontweight='bold'
    )
    
    plt.title('Profit Maximization System (PMS): Net Financial Impact vs Cutoff Threshold', fontweight='bold')
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='lower left', frameon=True)
    plt.tight_layout()
    fig6_path = os.path.join(IMAGES_DIR, 'fig6_financial_simulation.png')
    plt.savefig(fig6_path, dpi=300)
    plt.close()
    print(f"Saved: {fig6_path}")
    
    # Save financial summary to JSON
    fin_summary = {
        'optimal_threshold': float(opt_threshold),
        'targeted_population': int(opt_targeted),
        'retained_subscribers': int(opt_retained),
        'gross_revenue_saved': float(opt_rev_saved),
        'campaign_offer_cost': float(opt_cost),
        'fixed_system_cost': 200000.0,
        'max_net_profit_lift': float(max_net_profit),
        'campaign_net_roi': float(opt_roi),
        'baseline_churn_revenue_loss': 34493760.0
    }
    with open(os.path.join(IMAGES_DIR, 'financial_metrics.json'), 'w') as f:
        json.dump(fin_summary, f, indent=4)
        
    return fin_summary

def main():
    print("="*60)
    print("GCI 2026 WORLD FINAL ASSIGNMENT: TELECOM CHURN PREDICTION")
    print("="*60)
    
    df, cids = load_and_preprocess_data()
    generate_eda_figures(df)
    model, X_test, y_test, probs = train_and_evaluate_models(df)
    fin_summary = run_financial_simulation(y_test, probs, X_test.index, df)
    
    print("\n" + "="*60)
    print("ALL PIPELINE STAGES COMPLETED SUCCESSFULLY!")
    print("Generated 6 high-resolution charts in Completed/images/")
    print(f"Max Net Profit Lift: ${fin_summary['max_net_profit_lift']:,.2f}")
    print(f"Optimal Threshold: {fin_summary['optimal_threshold']:.2f}")
    print("="*60)

if __name__ == '__main__':
    main()
