from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CPP_QUESTIONS = (
    ROOT
    / "output/programming_kg/questions/xdu_cpp_verified_40/verified_questions.json"
)
DEFAULT_CPP_MAPPINGS = (
    ROOT
    / "output/programming_kg/questions/xdu_cpp_verified_40/mapping_course_cpp_v4/question_knowledge_links.json"
)
DEFAULT_GRAPH = (
    ROOT
    / "output/programming_kg/course_centered_v12_candidate_finalized/standard_graph.json"
)
DEFAULT_SOURCE_ROOT = Path(r"C:\Users\23189\Desktop\西电历年考试题整理\西电历年考试题整理")
DEFAULT_OUTPUT = ROOT / "output/programming_kg/questions/unified_v1_review"

JAVA_PDF_NAME = "JAVA真题.pdf"
JAVA_SHA256 = "9636dc60779e01ad15fc7cfc5125d12f73ae3ce3c0ee0626a09149d5906ef932"

# 两份 C++ 来源卷中有 5 道题仅排版不同、题干/选项/答案完全相同。
# 合并后保留两个来源记录，避免前端把同一道题展示两次。
CPP_DUPLICATE_TO_CANONICAL = {
    "XDU_CPP_COLLECTION_C_S01_Q03": "XDU_CPP_A_C_A_S01_Q04",
    "XDU_CPP_COLLECTION_C_S01_Q05": "XDU_CPP_A_C_A_S01_Q08",
    "XDU_CPP_COLLECTION_C_S01_Q06": "XDU_CPP_A_C_A_S01_Q09",
    "XDU_CPP_COLLECTION_C_S01_Q13": "XDU_CPP_A_C_A_S01_Q13",
    "XDU_CPP_COLLECTION_C_S01_Q17": "XDU_CPP_A_C_A_S01_Q16",
}


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(value)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def question_key(question: dict[str, Any]) -> str:
    options = "|".join(question.get("options", []))
    return normalized_text(
        f"{question.get('language', '')}|{question.get('stem', '')}|"
        f"{question.get('code', '')}|{options}"
    )


def java_question(
    *,
    question_id: str,
    year: int,
    page: int,
    section: str,
    question_number: str,
    qtype: str,
    stem: str,
    answer: str,
    stem_evidence: str,
    answer_evidence: str,
    source_file: Path,
    code: str = "",
    abilities: list[str] | None = None,
    difficulty: int = 3,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "type": qtype,
        "type_label": {
            "short_answer": "简答题",
            "code_reading": "代码阅读题",
            "code_fill": "编程填空题",
            "code_correction": "代码改错题",
        }[qtype],
        "language": "Java",
        "course_id": "course_java",
        "year": year,
        "stem": stem.strip(),
        "code": code.strip(),
        "options": [],
        "answer": answer.strip(),
        "analysis": "",
        "answer_source": "source_provided",
        "answer_kind": "inline_standard_answer",
        "answer_status": "source_verified_complete",
        "answer_confidence": 1.0,
        "answer_completeness": {
            "status": "complete",
            "confidence": 1.0,
            "reason": "题干与答案在同一原始 PDF 的同一题目区域中直接对应，并经页面可视复核。",
        },
        "formal_import_eligible": True,
        "difficulty": difficulty,
        "difficulty_label": {1: "简单", 2: "中等", 3: "较难", 4: "困难"}[difficulty],
        "abilities": abilities or ["概念理解"],
        "gold_knowledge_points": [],
        "source": {
            "kind": "inline_answer_pdf",
            "file": str(source_file),
            "sha256": JAVA_SHA256,
            "page": page,
            "section": section,
            "question_number": question_number,
            "parser": "manual_visual_review_v1",
        },
        "answer_pairing": {
            "status": "verified",
            "method": "same_pdf_question_region_visual_review",
            "source_file": str(source_file),
            "source_sha256": JAVA_SHA256,
            "question_page": page,
            "answer_page": page,
            "section": section,
            "question_number": question_number,
            "stem_evidence": stem_evidence.strip(),
            "answer_evidence": answer_evidence.strip(),
        },
    }


def build_java_questions(source_root: Path) -> list[dict[str, Any]]:
    source_file = source_root / "Java" / JAVA_PDF_NAME

    animal_context = """abstract class Animal {
    protected int id;
    double weight;
    public Animal(int id, double weight) {
        this.id = id;
        this.weight = weight;
    }
    abstract public void eat();
}

class Bird extends Animal implements Flyable {
    public Bird(int id, double weight) { super(id, weight); }
    public void eat() { weight += 1; }
    public void fly() { System.out.println("Bird " + id + " flys"); }
}

class Cat extends Animal implements Runner {
    String name;
    public Cat(int id, String name, double weight) {
        /* 填充1 */
    }
    /* 填充2 */
    /* 填充3 */
}
"""

    pet_context = """abstract class Pet {
    private String name;
    double weight;
    public Pet(String name, double weight) {
        this.name = name;
        this.weight = weight;
    }
    public abstract void raise();
    /* 填充1 */
}

class Dog extends Pet {
    public Dog(String name, double weight) { super(name, weight); }
    /* 填充2 */
}

class Cat extends Pet {
    public Cat(String name, double weight) { super(name, weight); }
    /* 填充3 */
}
"""

    return [
        java_question(
            question_id="XDU_JAVA_2019_SHORT_Q01",
            year=2019,
            page=1,
            section="简答题",
            question_number="1",
            qtype="short_answer",
            stem="说明类、对象及对象引用的概念，并举例。",
            answer="例如 Student s = new Student(); 中 Student 是类，new Student() 创建的是对象，s 是对象引用。",
            stem_evidence="1. 说明类、对象及对象引用的概念，并举例。",
            answer_evidence="Student s = new Student(); Student是类，new出来的是对象，s是对象引用",
            source_file=source_file,
            abilities=["概念理解", "示例说明"],
            difficulty=2,
        ),
        java_question(
            question_id="XDU_JAVA_2019_SHORT_Q02",
            year=2019,
            page=1,
            section="简答题",
            question_number="2",
            qtype="short_answer",
            stem="简述 Java 的多态性，以及运行时多态的三个必要条件。",
            answer="运行时多态的必要条件是：继承和方法重写、向上转型、动态绑定。",
            stem_evidence="2. 简述Java的多态性，以及运行时多态的三个必要条件。",
            answer_evidence="必要条件：1.继承和方法重写 2.向上转型 3.动态绑定",
            source_file=source_file,
            abilities=["概念理解"],
            difficulty=2,
        ),
        java_question(
            question_id="XDU_JAVA_2019_READ_Q01",
            year=2019,
            page=1,
            section="读程题",
            question_number="1",
            qtype="code_reading",
            stem="写出下列 Java 程序的运行结果。",
            code="""public class Test1 {
    public static void main(String[] args) {
        int i, s = 0;
        int a[] = {1,2,3,4,5,6,7,8,9};
        for (i = 0; i < a.length; i++) {
            if (a[i] % 2 == 0) {
                s += a[i];
                System.out.println("s = " + s);
            }
        }
    }
}""",
            answer="s = 2\ns = 6\ns = 12\ns = 20",
            stem_evidence="读程题1：Test1 对数组中的偶数进行累加，并在每次累加后输出 s。",
            answer_evidence="s = 2; s = 6; s = 12; s = 20",
            source_file=source_file,
            abilities=["代码阅读", "运行结果分析"],
        ),
        java_question(
            question_id="XDU_JAVA_2019_READ_Q02",
            year=2019,
            page=2,
            section="读程题",
            question_number="2",
            qtype="code_reading",
            stem="写出下列 Java 程序的运行结果。",
            code="""public class Test2 {
    static int x = 1;
    int y;
    Test2() { y++; }
    static { x++; }
    public static void main(String[] args) {
        Test2 st = new Test2();
        System.out.println("x = " + x);
        System.out.println("st.y = " + st.y);
        st = new Test2();
        System.out.println("x = " + x);
        System.out.println("st.y = " + st.y);
    }
}""",
            answer="x = 2\nst.y = 1\nx = 2\nst.y = 1",
            stem_evidence="读程题2：Test2 包含静态变量 x、实例变量 y、构造方法和静态初始化块。",
            answer_evidence="x = 2; st.y = 1; x = 2; st.y = 1",
            source_file=source_file,
            abilities=["代码阅读", "运行结果分析"],
        ),
        java_question(
            question_id="XDU_JAVA_2019_READ_Q03",
            year=2019,
            page=2,
            section="读程题",
            question_number="3",
            qtype="code_reading",
            stem="写出下列 Java 程序的运行结果。",
            code="""class Animal {
    String name;
    Animal(String name) {
        this.name = name;
        System.out.println("Animal " + name);
    }
    void eat() { System.out.println("Animal eat"); }
}

public class Cat extends Animal {
    int id;
    Cat(int id, String name) {
        super(name);
        this.id = id;
        System.out.println("Cat " + name);
    }
    void eat() {
        System.out.println("Cat name: " + name);
        System.out.println("Cat " + id + " eat");
    }
    public static void main(String[] args) {
        Animal a = new Cat(1, "mimi");
        a.eat();
    }
}""",
            answer="Animal mimi\nCat mimi\nCat name: mimi\nCat 1 eat",
            stem_evidence="读程题3：Animal 引用指向 Cat 对象并调用被重写的 eat 方法。",
            answer_evidence="Animal mimi; Cat mimi; Cat name: mimi; Cat 1 eat",
            source_file=source_file,
            abilities=["代码阅读", "运行结果分析", "多态分析"],
        ),
        java_question(
            question_id="XDU_JAVA_2019_FILL_Q01",
            year=2019,
            page=4,
            section="编程题1",
            question_number="填充1",
            qtype="code_fill",
            stem="在给定 Animal/Bird/Cat 程序中补全 Cat 构造方法：分别实现三个参数的传递赋值，完成对象初始化。",
            code=animal_context,
            answer="super(id, weight);\nthis.name = name;",
            stem_evidence="填充1：分别实现三个参数的传递赋值，完成对象初始化（2分）",
            answer_evidence="super(id, weight); this.name = name;",
            source_file=source_file,
            abilities=["代码补全", "程序设计"],
        ),
        java_question(
            question_id="XDU_JAVA_2019_FILL_Q02",
            year=2019,
            page=5,
            section="编程题1",
            question_number="填充2",
            qtype="code_fill",
            stem="在给定 Animal/Bird/Cat 程序中实现 Cat 的喂养方法，每次喂养使体重增加 20。",
            code=animal_context,
            answer="public void eat() { weight += 20; }",
            stem_evidence="填充2：实现喂养方法（返回值、参数和函数体），每次喂养体重增加20（2分）",
            answer_evidence="public void eat() { weight += 20; }",
            source_file=source_file,
            abilities=["代码补全", "程序设计"],
        ),
        java_question(
            question_id="XDU_JAVA_2019_FILL_Q03",
            year=2019,
            page=5,
            section="编程题1",
            question_number="填充3",
            qtype="code_fill",
            stem="在给定 Animal/Bird/Cat 程序中实现 Runner 接口方法，输出猫的 id、name 及必要描述。",
            code=animal_context,
            answer='public void run() { System.out.println("Cat " + id + " " + name + " is running..."); }',
            stem_evidence="填充3：实现接口方法，该方法中需输出猫的id、name及其他必要描述信息（3分）",
            answer_evidence='public void run() { System.out.println("Cat " + id + " " + name + " is running..."); }',
            source_file=source_file,
            abilities=["代码补全", "程序设计"],
        ),
        java_question(
            question_id="XDU_JAVA_2019_FILL_Q04",
            year=2019,
            page=5,
            section="编程题1",
            question_number="填充4",
            qtype="code_fill",
            stem="补全 raiseAllPets(Animal[] animals)，遍历数组并喂养所有宠物。",
            code="""private static void raiseAllPets(Animal[] animals) {
    /* 填充4 */
}""",
            answer="for (Animal a : animals) { a.eat(); }",
            stem_evidence="填充4：喂养所有的宠物（4分）",
            answer_evidence="for (Animal a : animals) { a.eat(); }",
            source_file=source_file,
            abilities=["代码补全", "程序设计"],
        ),
        java_question(
            question_id="XDU_JAVA_2018_CORRECT_Q01",
            year=2018,
            page=9,
            section="改错题",
            question_number="1",
            qtype="code_correction",
            stem="下面 Java 程序中存在 6 处编译错误，指出错误位置、说明原因并改正。",
            code="""abstract class Person {
    private String name;
    public String getName() { return name }
    public abstract boolean isGraduated() throws NameNotExistException {}
}
class NameNotExistException extends RuntimeException {}
class Student extends Person {
    final int studentID;
    public boolean isGraduated() throws Exception { return false; }
    public String elective(final String className) {
        className = "Java 程序设计";
        return className;
    }
}
public class TestResult {
    public static void main(String[] args) {
        Student p = new Student();
        System.out.print(p.getName() + "选修了" + p.elective() + "课程");
    }
}""",
            answer=(
                "1. getName 方法中的 return name 后缺少分号。\n"
                "2. Student 重写 isGraduated 时不能声明比父类方法更宽泛的检查型异常 Exception。\n"
                "3. elective 的形参 className 被 final 修饰，不能重新赋值。\n"
                "4. final 实例变量 studentID 必须在声明处或每个构造方法中初始化。\n"
                "5. 调用 elective 时缺少 String 参数。\n"
                "6. abstract 方法 isGraduated 不能有方法体，应删除花括号并以分号结束。"
            ),
            stem_evidence="改错题：程序存在6处编译错误，指出错误位置、说明错误原因并改正。",
            answer_evidence="页面列出第3、10、16、9、24、4行的六项完整错误原因与修改方向。",
            source_file=source_file,
            abilities=["代码审查", "错误分析", "程序调试"],
            difficulty=4,
        ),
        java_question(
            question_id="XDU_JAVA_2018_FILL_Q01",
            year=2018,
            page=10,
            section="编程题1",
            question_number="填充1",
            qtype="code_fill",
            stem="在 Pet 类中实现 getInfo，按指定格式返回宠物名称和体重信息。",
            code=pet_context,
            answer='public String getInfo() { return "name = " + this.name + ", weight = " + this.weight; }',
            stem_evidence="填充1：输出宠物类的名称和重量信息，并以一定的格式分隔开（2分）",
            answer_evidence='public String getInfo() { return "name = " + this.name + ", weight = " + this.weight; }',
            source_file=source_file,
            abilities=["代码补全", "程序设计"],
        ),
        java_question(
            question_id="XDU_JAVA_2018_FILL_Q02",
            year=2018,
            page=10,
            section="编程题1",
            question_number="填充2",
            qtype="code_fill",
            stem="在 Dog 类中重写 raise 方法，使每次调用后小狗体重增加 0.2。",
            code=pet_context,
            answer="public void raise() { weight = weight + 0.2; }",
            stem_evidence="填充2：填写下一行中等号右边部分，使每次调用该方法小狗体重增加0.2",
            answer_evidence="weight = weight + 0.2;",
            source_file=source_file,
            abilities=["代码补全", "程序设计"],
        ),
        java_question(
            question_id="XDU_JAVA_2018_FILL_Q03",
            year=2018,
            page=11,
            section="编程题1",
            question_number="填充3",
            qtype="code_fill",
            stem="在 Cat 类中创建 raise 方法，使小猫每次喂养体重增加 0.1。",
            code=pet_context,
            answer="public void raise() { weight += 0.1; }",
            stem_evidence="填充3：创建相应方法，并使小猫每次喂养体重增加0.1",
            answer_evidence="public void raise() { weight += 0.1; }",
            source_file=source_file,
            abilities=["代码补全", "程序设计"],
        ),
        java_question(
            question_id="XDU_JAVA_2018_FILL_Q04",
            year=2018,
            page=11,
            section="编程题1",
            question_number="填充4",
            qtype="code_fill",
            stem="补全 raiseAllPets(List<Pet> p)：为列表中的每个宠物喂养一次，并输出名称和体重。",
            code="""public static void raiseAllPets(List<Pet> p) {
    /* 填充4 */
}""",
            answer="for (Pet pet : p) { pet.raise(); System.out.println(pet.getInfo()); }",
            stem_evidence="填充4：为列表p中的每个宠物喂养一次，并输出宠物的名称和体重",
            answer_evidence="for (Pet pet : p) { pet.raise(); System.out.println(pet.getInfo()); }",
            source_file=source_file,
            abilities=["代码补全", "程序设计"],
        ),
    ]


JAVA_MAPPING_SPECS: dict[str, list[tuple[str, str, str]]] = {
    "XDU_JAVA_2019_SHORT_Q01": [
        ("course_java__curriculum_E1_1", "primary", "题目直接考查类的概念。"),
        ("course_java__curriculum_E1_2", "secondary", "题目同时要求说明对象。"),
        ("course_java__curriculum_A4_2", "secondary", "题目同时要求说明对象引用。"),
    ],
    "XDU_JAVA_2019_SHORT_Q02": [
        ("course_java__curriculum_E4_1", "primary", "运行时多态的核心机制是动态绑定。"),
        ("course_java__curriculum_E3_2", "secondary", "题目答案明确包含方法重写。"),
        ("course_java__curriculum_E4_2", "secondary", "题目答案明确包含向上转型。"),
    ],
    "XDU_JAVA_2019_READ_Q01": [
        ("course_java__curriculum_D2_1", "primary", "程序遍历并读取数组元素。"),
        ("course_java__curriculum_B2_1", "secondary", "使用 for 循环遍历数组。"),
        ("course_java__curriculum_B1_2", "secondary", "使用 if 判断偶数。"),
    ],
    "XDU_JAVA_2019_READ_Q02": [
        ("course_java__curriculum_E1_5", "primary", "题目核心是静态变量和静态初始化块只初始化一次。"),
        ("course_java__curriculum_E1_6", "secondary", "两次创建对象用于比较实例成员状态。"),
    ],
    "XDU_JAVA_2019_READ_Q03": [
        ("course_java__curriculum_E4_1", "primary", "父类引用调用子类重写方法体现动态绑定。"),
        ("course_java__curriculum_E3_2", "secondary", "Cat 重写 Animal.eat。"),
        ("course_java__curriculum_E4_2", "secondary", "Animal 引用指向 Cat 对象体现向上转型。"),
    ],
    "XDU_JAVA_2019_FILL_Q01": [
        ("course_java__curriculum_E1_4", "primary", "题目要求补全子类构造方法。"),
        ("course_java__SyntaxRule_super", "secondary", "答案通过 super 调用父类构造方法。"),
        ("course_java__curriculum_E1_3", "secondary", "答案完成 name 属性赋值。"),
    ],
    "XDU_JAVA_2019_FILL_Q02": [
        ("course_java__curriculum_E3_2", "primary", "Cat 实现父类抽象 eat 方法。"),
        ("course_java__curriculum_E1_3", "secondary", "方法修改对象 weight 属性。"),
    ],
    "XDU_JAVA_2019_FILL_Q03": [
        ("course_java__curriculum_E5_2", "primary", "题目明确要求实现 Runner 接口方法。"),
        ("course_java__curriculum_E3_2", "secondary", "实现接口方法属于方法实现/重写。"),
        ("course_java__curriculum_A3_2", "secondary", "方法通过 println 输出信息。"),
    ],
    "XDU_JAVA_2019_FILL_Q04": [
        ("course_java__curriculum_B2_1", "primary", "答案使用增强 for 循环遍历数组。"),
        ("course_java__curriculum_E4_1", "secondary", "对 Animal 引用调用 eat 会触发动态绑定。"),
        ("course_java__curriculum_D2_1", "secondary", "遍历对象数组。"),
    ],
    "XDU_JAVA_2018_CORRECT_Q01": [
        ("course_java__curriculum_F2", "primary", "综合改错题主要考查编译错误识别与调试。"),
        ("course_java__curriculum_E5_4", "secondary", "包含抽象方法声明错误。"),
        ("course_java__curriculum_F1_1", "secondary", "包含重写方法异常声明范围错误。"),
    ],
    "XDU_JAVA_2018_FILL_Q01": [
        ("course_java__curriculum_E1_3", "primary", "题目要求实现对象信息方法。"),
        ("course_java__curriculum_C1_2", "secondary", "方法构造并返回字符串结果。"),
        ("course_java__curriculum_D1_1", "secondary", "返回值是格式化字符串。"),
    ],
    "XDU_JAVA_2018_FILL_Q02": [
        ("course_java__curriculum_E3_2", "primary", "Dog 重写抽象 raise 方法。"),
        ("course_java__curriculum_E1_3", "secondary", "方法更新 weight 属性。"),
    ],
    "XDU_JAVA_2018_FILL_Q03": [
        ("course_java__curriculum_E3_2", "primary", "Cat 重写抽象 raise 方法。"),
        ("course_java__curriculum_E1_3", "secondary", "方法更新 weight 属性。"),
    ],
    "XDU_JAVA_2018_FILL_Q04": [
        ("course_java__curriculum_D2_2", "primary", "题目遍历 List<Pet> 列表。"),
        ("course_java__curriculum_B2_1", "secondary", "答案使用增强 for 循环。"),
        ("course_java__curriculum_E4_1", "secondary", "对 Pet 引用调用 raise 体现动态绑定。"),
    ],
}


def make_java_mappings(
    questions: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for question in questions:
        specs = JAVA_MAPPING_SPECS.get(question["question_id"], [])
        links = []
        for rank, (node_id, role, evidence) in enumerate(specs, 1):
            node = nodes[node_id]
            links.append(
                {
                    "knowledge_node_id": node_id,
                    "knowledge_name": node["name"],
                    "knowledge_type": node["type"],
                    "role": role,
                    "confidence": 1.0 if role == "primary" else 0.95,
                    "evidence": evidence,
                    "rank": rank,
                    "role_weight": 1.0 if role == "primary" else 0.6,
                    "mapping_status": "review_candidate",
                }
            )
        records.append(
            {
                "question_id": question["question_id"],
                "method": "manual_source_evidence_alignment_v1",
                "candidate_count": len(links),
                "links": links,
                "language_context": "Java",
                "verified_answer_context_used": True,
            }
        )
    return records


def normalize_cpp_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_by_id: dict[str, dict[str, Any]] = {}
    for question in questions:
        original_id = question["question_id"]
        canonical_id = CPP_DUPLICATE_TO_CANONICAL.get(original_id, original_id)
        occurrence = {
            "original_question_id": original_id,
            "source": question.get("source", {}),
            "answer_pairing": question.get("answer_pairing", {}),
        }
        if canonical_id in normalized_by_id:
            normalized_by_id[canonical_id]["source_occurrences"].append(occurrence)
            continue
        value = dict(question)
        value["question_id"] = canonical_id
        value["course_id"] = "course_cpp"
        value["source_occurrences"] = [occurrence]
        normalized_by_id[canonical_id] = value
    return list(normalized_by_id.values())


def normalize_cpp_mappings(
    mappings: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    normalized_by_id: dict[str, dict[str, Any]] = {}
    for record in mappings:
        original_id = record["question_id"]
        canonical_id = CPP_DUPLICATE_TO_CANONICAL.get(original_id, original_id)
        if canonical_id in normalized_by_id:
            normalized_by_id[canonical_id].setdefault("original_mapping_ids", []).append(
                original_id
            )
            continue
        value = dict(record)
        value["question_id"] = canonical_id
        value["method"] = "prior_mapping_v4_rebased_to_current_graph"
        value["mapping_source"] = "xdu_cpp_verified_40/mapping_course_cpp_v4"
        value["original_mapping_ids"] = [original_id]
        links = []
        for rank, link in enumerate(record.get("links", [])[:3], 1):
            node_id = link["knowledge_node_id"]
            if node_id not in nodes:
                continue
            item = dict(link)
            item["rank"] = rank
            item["role"] = "primary" if rank == 1 else "secondary"
            item["role_weight"] = 1.0 if rank == 1 else 0.6
            item["mapping_status"] = "review_candidate"
            links.append(item)
        value["links"] = links
        normalized_by_id[canonical_id] = value

    # 旧映射 Q02 被干扰选项“封装”带偏；Q14 的“对象”粒度过粗。
    overrides = {
        "XDU_CPP_A_C_A_S01_Q02": [
            (
                "course_cpp__curriculum_E",
                "面向对象编程",
                "KnowledgeDomain",
                "题目整体考查面向对象程序设计的主要特征，而不是单独考查选项中的封装。",
            )
        ],
        "XDU_CPP_A_C_A_S01_Q14": [
            (
                "course_cpp__curriculum_E3_1",
                "父类与子类",
                "KnowledgePoint",
                "赋值兼容规则由基类与派生类的方向关系决定。",
            )
        ],
    }
    for question_id, specs in overrides.items():
        record = normalized_by_id[question_id]
        record["method"] = "manual_semantic_review_v1"
        record["links"] = [
            {
                "knowledge_node_id": node_id,
                "knowledge_name": name,
                "knowledge_type": node_type,
                "role": "primary" if rank == 1 else "secondary",
                "confidence": 1.0,
                "evidence": evidence,
                "rank": rank,
                "role_weight": 1.0 if rank == 1 else 0.6,
                "mapping_status": "review_candidate",
            }
            for rank, (node_id, name, node_type, evidence) in enumerate(specs, 1)
        ]
    return list(normalized_by_id.values())


def excluded_items(source_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "scope": "source_files",
            "files": [
                str(source_root / "C++" / "2021期末考试A卷.pdf"),
                str(source_root / "C++" / "2021期末考试B卷.pdf"),
                str(source_root / "C++" / "2022期末考试A卷.pdf"),
            ],
            "reason": "试卷包含题干但没有可直接核验的来源答案；不独立生成答案。",
            "status": "excluded_pending_source_answer",
        },
        {
            "scope": "source_files",
            "files": [
                str(source_root / "Java" / "Java2022二学位试题-王煦.pdf"),
                str(source_root / "Java" / "Java2022试题A-王煦.pdf"),
            ],
            "reason": "试卷包含题干但没有来源答案。",
            "status": "excluded_pending_source_answer",
        },
        {
            "scope": "JAVA真题.pdf部分题目",
            "files": [str(source_root / "Java" / JAVA_PDF_NAME)],
            "reason": (
                "仅纳入 2019A 和 2018A 中题干与答案完整对应且答案本身可成立的 14 道题。"
                "空白输出、答案项缺失、只给行号未说明改法、2019 编程填空5的不可编译来源答案，"
                "以及 2020A 无答案题全部排除。"
            ),
            "status": "partially_accepted",
        },
        {
            "scope": "数据结构试卷与代码",
            "files": [str(source_root / "数据结构")],
            "reason": "试卷无来源答案；45 个代码文件缺少可恢复的完整题干，不能只凭代码反推题目。",
            "status": "excluded_incomplete_question_answer_pair",
        },
        {
            "scope": "Python代码集合",
            "files": [str(source_root / "Python")],
            "reason": "89 个 Python 文件仅有解题代码，缺少完整题干和来源答案说明。",
            "status": "excluded_incomplete_question_answer_pair",
        },
        {
            "scope": "研究索引",
            "files": [str(source_root / "_research")],
            "reason": "目录为检索和索引材料，不是习题来源。",
            "status": "excluded_non_question_material",
        },
    ]


def validate_source(question: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    source_records = [
        {
            "source": question.get("source", {}),
            "answer_pairing": question.get("answer_pairing", {}),
        }
    ]
    if question.get("source_occurrences"):
        source_records = question["source_occurrences"]
    for index, record in enumerate(source_records, 1):
        source = record.get("source", {})
        source_file = Path(source.get("file", ""))
        if not source_file.is_file():
            errors.append(f"source_file_missing:{index}")
        elif source.get("sha256") and sha256_file(source_file) != source["sha256"]:
            errors.append(f"source_sha256_mismatch:{index}")
        if record.get("answer_pairing", {}).get("status") != "verified":
            errors.append(f"answer_pairing_not_verified:{index}")
    if not question.get("stem", "").strip():
        errors.append("empty_stem")
    if not question.get("answer", "").strip():
        errors.append("empty_answer")
    if question.get("answer_status") != "source_verified_complete":
        errors.append("answer_not_source_verified_complete")
    return errors


def build_review_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 统一来源验证习题库复核报告",
        "",
        "> 本报告仅用于人工复核。本轮没有执行 Neo4j 入库。",
        "",
        "## 一、结果概览",
        "",
        f"- 来源验证题目：{report['counts']['verified_questions']} 道",
        f"- C++：{report['counts']['by_language'].get('C++', 0)} 道",
        f"- Java：{report['counts']['by_language'].get('Java', 0)} 道",
        f"- 已合并的重复来源题：{report['counts']['merged_duplicate_sources']} 道",
        f"- 已生成可信知识点映射：{report['counts']['mapped_questions']} 道",
        f"- 待映射人工复核：{report['counts']['unmapped_questions']} 道",
        f"- 可安全进入下一步入库候选：{report['counts']['formal_candidate_questions']} 道",
        f"- 其中宽粒度主映射：{report['counts']['broad_primary_mappings']} 道",
        "",
        "## 二、准入规则",
        "",
        "1. 题干必须完整；大题拆分时保留解题所需公共上下文。",
        "2. 答案必须能在同一来源材料中直接核验，不独立生成缺失答案。",
        "3. 每道题与答案按来源、题号、页码和证据片段绑定。",
        "4. 知识点映射必须引用当前五课程图谱中的真实节点 ID。",
        "5. 每道已映射题恰有一个 primary，最多两个 secondary。",
        "",
        "## 三、待人工确认",
        "",
    ]
    if report["unmapped_question_ids"]:
        lines.extend(
            [f"- `{question_id}`：缺少足够精确的课程局部知识点，不进行硬映射。" for question_id in report["unmapped_question_ids"]]
        )
    else:
        lines.append("- 无。")
    for item in report["broad_primary_mapping_items"]:
        lines.append(
            f"- `{item['question_id']}`：当前主映射为{item['knowledge_type']}“{item['knowledge_name']}”，"
            "语义合理但粒度宽于 KnowledgePoint。"
        )
    lines.extend(
        [
            "",
            "## 四、排除范围",
            "",
            "- 无来源答案的正式试卷保留在候选区，不进入正式题库。",
            "- 仅有代码、缺少完整题干的 Python/数据结构文件不反向猜题。",
            "- Java 真题中空白答案、答案不完整或输出存在不确定性的题目不纳入。",
            "",
            "## 五、质量审计",
            "",
            f"- 审计通过：{'是' if report['audit_passed'] else '否'}",
            f"- 重复题目：{report['audit']['duplicate_question_count']} 道",
            f"- 来源或答案配对错误：{report['audit']['question_error_count']} 道",
            f"- 无效知识点 ID：{report['audit']['invalid_mapping_node_count']} 个",
            f"- 映射角色约束错误：{report['audit']['mapping_role_error_count']} 道",
            "",
            "人工确认后，下一步才运行习题导入脚本。",
            "",
        ]
    )
    return "\n".join(lines)


def compact_markdown(value: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", value or "").strip().replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_item_review_markdown(
    questions: list[dict[str, Any]], mappings_by_id: dict[str, dict[str, Any]]
) -> str:
    lines = [
        "# 习题逐题复核清单",
        "",
        "> 所有题目均已完成来源文件和答案配对校验；映射状态仍为复核候选，确认后再入库。",
        "",
        "| 序号 | 题目 ID | 课程 | 类型 | 题干摘要 | 答案摘要 | 主知识点 | 次知识点 | 来源 | 状态 |",
        "|---:|---|---|---|---|---|---|---|---|---|",
    ]
    for index, question in enumerate(questions, 1):
        mapping = mappings_by_id.get(question["question_id"], {})
        links = mapping.get("links", [])
        primary = next(
            (link["knowledge_name"] for link in links if link.get("role") == "primary"),
            "-",
        )
        secondary = "、".join(
            link["knowledge_name"]
            for link in links
            if link.get("role") == "secondary"
        ) or "-"
        source = question.get("source", {})
        source_label = f"{Path(source.get('file', '')).name}"
        if source.get("page"):
            source_label += f" P{source['page']}"
        if source.get("question_number"):
            source_label += f" / {source['question_number']}"
        primary_link = next(
            (link for link in links if link.get("role") == "primary"), None
        )
        if primary == "-":
            status = "待映射复核"
        elif primary_link and primary_link.get("knowledge_type") != "KnowledgePoint":
            status = "可入库候选（宽粒度）"
        else:
            status = "可入库候选"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    f"`{question['question_id']}`",
                    question.get("language", ""),
                    question.get("type_label", question.get("type", "")),
                    compact_markdown(question.get("stem", "")),
                    compact_markdown(question.get("answer", ""), 70),
                    primary,
                    secondary,
                    compact_markdown(source_label, 55),
                    status,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 复核说明",
            "",
            "- C++ 重复题已合并，但每道题的 `source_occurrences` 仍保留所有原始来源。",
            "- Java 编程填空题的 JSON 中包含完成该小题所需的公共代码上下文。",
            "- 两道待映射题没有被删除，只是不会进入本轮正式入库候选。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建统一的来源验证习题候选库并执行完整性审计。")
    parser.add_argument("--cpp-questions", type=Path, default=DEFAULT_CPP_QUESTIONS)
    parser.add_argument("--cpp-mappings", type=Path, default=DEFAULT_CPP_MAPPINGS)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in graph["nodes"]}
    cpp_questions = normalize_cpp_questions(
        json.loads(args.cpp_questions.read_text(encoding="utf-8"))
    )
    cpp_mappings = normalize_cpp_mappings(
        json.loads(args.cpp_mappings.read_text(encoding="utf-8")), nodes
    )
    java_questions = build_java_questions(args.source_root)
    java_mappings = make_java_mappings(java_questions, nodes)

    questions: list[dict[str, Any]] = []
    duplicate_ids: list[str] = []
    seen_keys: dict[str, str] = {}
    for question in cpp_questions + java_questions:
        key = question_key(question)
        if key in seen_keys:
            duplicate_ids.append(question["question_id"])
            continue
        seen_keys[key] = question["question_id"]
        questions.append(question)

    mappings = cpp_mappings + java_mappings
    mappings_by_id = {record["question_id"]: record for record in mappings}
    question_errors = {
        question["question_id"]: errors
        for question in questions
        if (errors := validate_source(question))
    }
    invalid_mapping_nodes: list[dict[str, str]] = []
    mapping_role_errors: list[str] = []
    mapped_question_ids: list[str] = []
    for question in questions:
        record = mappings_by_id.get(question["question_id"], {})
        links = record.get("links", [])
        for link in links:
            node_id = link.get("knowledge_node_id", "")
            if node_id not in nodes:
                invalid_mapping_nodes.append(
                    {"question_id": question["question_id"], "knowledge_node_id": node_id}
                )
            elif nodes[node_id].get("course_id") != question.get("course_id"):
                invalid_mapping_nodes.append(
                    {
                        "question_id": question["question_id"],
                        "knowledge_node_id": node_id,
                        "reason": "cross_course_mapping",
                    }
                )
        primary_count = sum(link.get("role") == "primary" for link in links)
        secondary_count = sum(link.get("role") == "secondary" for link in links)
        if links and (primary_count != 1 or secondary_count > 2 or len(links) > 3):
            mapping_role_errors.append(question["question_id"])
        if links and primary_count == 1 and not any(
            item["question_id"] == question["question_id"] for item in invalid_mapping_nodes
        ):
            mapped_question_ids.append(question["question_id"])

    formal_candidates = [
        question
        for question in questions
        if question["question_id"] in mapped_question_ids
        and question["question_id"] not in question_errors
        and question["question_id"] not in mapping_role_errors
    ]
    formal_ids = {question["question_id"] for question in formal_candidates}
    formal_mappings = [
        mappings_by_id[question_id]
        for question_id in mapped_question_ids
        if question_id in formal_ids
    ]
    # 正式精确题库只接收主映射落到具体 KnowledgePoint 的题目。
    # 领域/单元级映射虽然可能语义合理，但粒度不足，继续保留在复核候选中。
    precise_mapping_ids = {
        record["question_id"]
        for record in formal_mappings
        if any(
            link.get("role") == "primary"
            and link.get("knowledge_type") == "KnowledgePoint"
            for link in record.get("links", [])
        )
    }
    precise_candidates = [
        question
        for question in formal_candidates
        if question["question_id"] in precise_mapping_ids
    ]
    precise_mappings = [
        {
            **record,
            "links": [
                link
                for link in record.get("links", [])
                if link.get("knowledge_type") == "KnowledgePoint"
            ],
        }
        for record in formal_mappings
        if record["question_id"] in precise_mapping_ids
    ]
    unmapped_ids = [
        question["question_id"]
        for question in questions
        if question["question_id"] not in mapped_question_ids
    ]
    unmapped_questions = [
        question for question in questions if question["question_id"] in unmapped_ids
    ]
    broad_primary_mapping_items = []
    for record in mappings:
        primary = next(
            (link for link in record.get("links", []) if link.get("role") == "primary"),
            None,
        )
        if primary and primary.get("knowledge_type") != "KnowledgePoint":
            broad_primary_mapping_items.append(
                {
                    "question_id": record["question_id"],
                    "knowledge_node_id": primary["knowledge_node_id"],
                    "knowledge_name": primary["knowledge_name"],
                    "knowledge_type": primary["knowledge_type"],
                }
            )

    audit = {
        "duplicate_question_count": len(duplicate_ids),
        "duplicate_question_ids": duplicate_ids,
        "question_error_count": len(question_errors),
        "question_errors": question_errors,
        "invalid_mapping_node_count": len(invalid_mapping_nodes),
        "invalid_mapping_nodes": invalid_mapping_nodes,
        "mapping_role_error_count": len(mapping_role_errors),
        "mapping_role_error_question_ids": mapping_role_errors,
    }
    audit_passed = not any(
        [duplicate_ids, question_errors, invalid_mapping_nodes, mapping_role_errors]
    )
    report = {
        "schema_version": "unified_verified_questions_review_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph": str(args.graph.resolve()),
        "source_root": str(args.source_root.resolve()),
        "neo4j_import_executed": False,
        "counts": {
            "verified_questions": len(questions),
            "by_language": dict(Counter(question["language"] for question in questions)),
            "merged_duplicate_sources": len(CPP_DUPLICATE_TO_CANONICAL),
            "mapped_questions": len(mapped_question_ids),
            "unmapped_questions": len(unmapped_ids),
            "formal_candidate_questions": len(formal_candidates),
            "formal_candidate_links": sum(
                len(record.get("links", [])) for record in formal_mappings
            ),
            "precise_formal_questions": len(precise_candidates),
            "precise_formal_links": sum(
                len(record.get("links", [])) for record in precise_mappings
            ),
            "broad_primary_mappings": len(broad_primary_mapping_items),
        },
        "unmapped_question_ids": unmapped_ids,
        "broad_primary_mapping_items": broad_primary_mapping_items,
        "audit_passed": audit_passed,
        "audit": audit,
        "notes": [
            "C++ 40 题来自同卷编号答案键，复用 v4 映射并校验为当前图谱真实 ID。",
            "Java 14 题由 JAVA真题.pdf 页面直接核验；编程填空题保留必要公共代码上下文。",
            "未映射题保留在来源验证题库和复核清单，不进入正式入库候选。",
        ],
    }

    output_dir = args.output_dir
    atomic_write_json(output_dir / "verified_questions.json", questions)
    atomic_write_json(output_dir / "question_knowledge_links.json", mappings)
    atomic_write_json(output_dir / "formal_mapped_questions.json", formal_candidates)
    atomic_write_json(output_dir / "formal_question_knowledge_links.json", formal_mappings)
    atomic_write_json(output_dir / "formal_precise_questions.json", precise_candidates)
    atomic_write_json(
        output_dir / "formal_precise_question_knowledge_links.json",
        precise_mappings,
    )
    atomic_write_json(output_dir / "unmapped_questions_for_review.json", unmapped_questions)
    atomic_write_json(output_dir / "excluded_sources_and_items.json", excluded_items(args.source_root))
    atomic_write_json(output_dir / "question_review_report.json", report)
    atomic_write_json(output_dir / "question_audit_report.json", audit)
    atomic_write_text(output_dir / "习题统一复核报告.md", build_review_markdown(report))
    atomic_write_text(
        output_dir / "习题逐题复核清单.md",
        build_item_review_markdown(questions, mappings_by_id),
    )

    print(f"来源验证题目：{len(questions)}")
    print(f"已映射题目：{len(mapped_question_ids)}")
    print(f"待映射复核：{len(unmapped_ids)}")
    print(f"正式入库候选：{len(formal_candidates)}")
    print(f"精确知识点入库题目：{len(precise_candidates)}")
    print(f"质量审计通过：{audit_passed}")
    print(f"复核报告：{output_dir / '习题统一复核报告.md'}")
    print("Neo4j 入库：未执行")


if __name__ == "__main__":
    main()
