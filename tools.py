"""
LangChain tools for the VIP Data Concierge agent.
Each tool maps to a specific query the AI can execute via Function Calling.
The department parameter ensures data isolation — the agent can only
access the database that matches the authenticated user's department.
"""

from langchain_core.tools import tool
from db import execute_read_query


@tool
def list_employees(department: str) -> str:
    """List all employees. Only available to HR department users.
    Args:
        department: The authenticated user's department (must be 'hr').
    """
    rows = execute_read_query(
        "hr",
        "SELECT name, department, position, salary, hire_date "
        "FROM employees ORDER BY name"
    )
    if not rows:
        return "No employees found."

    lines = ["Employees:"]
    for r in rows:
        lines.append(
            f"- {r['name']} | {r['department']} | {r['position']} "
            f"| ${r['salary']:,.2f} | Hired: {r['hire_date']}"
        )
    return "\n".join(lines)


@tool
def search_employee(department: str, name: str) -> str:
    """Search for an employee by name. Only available to HR department users.
    Args:
        department: The authenticated user's department (must be 'hr').
        name: Full or partial name to search for.
    """
    rows = execute_read_query(
        "hr",
        f"SELECT name, department, position, salary, hire_date "
        f"FROM employees WHERE LOWER(name) LIKE LOWER('%{name}%')"
    )
    if not rows:
        return f"No employee found matching '{name}'."

    lines = [f"Search results for '{name}':"]
    for r in rows:
        lines.append(
            f"- {r['name']} | {r['department']} | {r['position']} "
            f"| ${r['salary']:,.2f} | Hired: {r['hire_date']}"
        )
    return "\n".join(lines)


@tool
def get_department_salary_summary(department: str, dept_filter: str) -> str:
    """Get salary summary for a department. Only available to HR department users.
    Args:
        department: The authenticated user's department (must be 'hr').
        dept_filter: Department to summarize (e.g. 'Engineering', 'Marketing').
    """
    rows = execute_read_query(
        "hr",
        f"SELECT COUNT(*) as count, AVG(salary) as avg_salary, "
        f"MIN(salary) as min_salary, MAX(salary) as max_salary "
        f"FROM employees WHERE LOWER(department) = LOWER('{dept_filter}')"
    )
    if not rows or rows[0]["count"] == 0:
        return f"No employees found in department '{dept_filter}'."

    r = rows[0]
    return (
        f"Salary summary for {dept_filter}:\n"
        f"- Headcount: {r['count']}\n"
        f"- Average: ${float(r['avg_salary']):,.2f}\n"
        f"- Range: ${float(r['min_salary']):,.2f} - ${float(r['max_salary']):,.2f}"
    )


@tool
def list_invoices(department: str, status: str = "") -> str:
    """List invoices, optionally filtered by status. Only available to Finance department users.
    Args:
        department: The authenticated user's department (must be 'finance').
        status: Optional filter — 'paid', 'pending', or 'overdue'. Empty for all.
    """
    query = (
        "SELECT vendor, amount, status, due_date, department "
        "FROM invoices"
    )
    if status:
        query += f" WHERE LOWER(status) = LOWER('{status}')"
    query += " ORDER BY due_date"

    rows = execute_read_query("finance", query)
    if not rows:
        return f"No invoices found{' with status ' + status if status else ''}."

    lines = [f"Invoices{' (' + status + ')' if status else ''}:"]
    for r in rows:
        lines.append(
            f"- {r['vendor']} | ${r['amount']:,.2f} | {r['status']} "
            f"| Due: {r['due_date']} | Dept: {r['department']}"
        )
    return "\n".join(lines)


@tool
def get_budget_summary(department: str, dept_filter: str = "") -> str:
    """Get budget allocation and spending. Only available to Finance department users.
    Args:
        department: The authenticated user's department (must be 'finance').
        dept_filter: Optional department to filter. Empty for all departments.
    """
    query = (
        "SELECT department, quarter, allocated, spent "
        "FROM budgets"
    )
    if dept_filter:
        query += f" WHERE LOWER(department) = LOWER('{dept_filter}')"
    query += " ORDER BY department"

    rows = execute_read_query("finance", query)
    if not rows:
        return f"No budget data found{' for ' + dept_filter if dept_filter else ''}."

    lines = ["Budget Summary:"]
    for r in rows:
        remaining = float(r["allocated"]) - float(r["spent"])
        pct = (float(r["spent"]) / float(r["allocated"])) * 100
        lines.append(
            f"- {r['department']} ({r['quarter']}): "
            f"${float(r['allocated']):,.2f} allocated, "
            f"${float(r['spent']):,.2f} spent ({pct:.0f}%), "
            f"${remaining:,.2f} remaining"
        )
    return "\n".join(lines)


@tool
def get_overdue_invoices(department: str) -> str:
    """Get all overdue invoices. Only available to Finance department users.
    Args:
        department: The authenticated user's department (must be 'finance').
    """
    rows = execute_read_query(
        "finance",
        "SELECT vendor, amount, due_date, department "
        "FROM invoices WHERE status = 'overdue' ORDER BY due_date"
    )
    if not rows:
        return "No overdue invoices found."

    total = sum(float(r["amount"]) for r in rows)
    lines = [f"Overdue Invoices (Total: ${total:,.2f}):"]
    for r in rows:
        lines.append(
            f"- {r['vendor']} | ${float(r['amount']):,.2f} "
            f"| Due: {r['due_date']} | Dept: {r['department']}"
        )
    return "\n".join(lines)


# Tool registry by department
HR_TOOLS = [list_employees, search_employee, get_department_salary_summary]
FINANCE_TOOLS = [list_invoices, get_budget_summary, get_overdue_invoices]

TOOLS_BY_DEPARTMENT = {
    "hr": HR_TOOLS,
    "finance": FINANCE_TOOLS,
}
