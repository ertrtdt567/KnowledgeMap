# 正式题库题目-知识点全量复核报告

- 复核日期：2026-07-18
- 复核方式：题干、完整代码/选项、标准答案和映射证据的全量语义复核。
- 判定规则：只保留直接考查的知识点；仅背景相关或可能用到的知识点不作为正确映射。

## 结果

- 题目：45 道；映射记录：45 条；映射关系：73 条。
- 正确：73；错误：0；待确认：0。
- 已入库映射准确率：100.00%。
- 题目映射覆盖率：100.00%。
- 说明：该准确率衡量当前已入库关系是否正确；不把未被映射的潜在知识点视为错误，因而不宣称独立的召回率。

## 逐条记录

| 题目 ID | 课程 | 知识点 | 角色 | 判定 | 直接证据 |
| --- | --- | --- | --- | --- | --- |
| XDU_CPP_A_C_A_S01_Q03 | course_cpp | 字符串 | primary | correct | cin>> 读取字符串时以空白字符为分隔符，输入 'Microsoft Visual Studio 6.0!' 中的第一个单词 'Microsoft' 被读取，遇到空格停止，因此 str 结果为 'Microsoft'。 |
| XDU_CPP_A_C_A_S01_Q04 | course_cpp | 缺省参数 | primary | correct | 函数原型中int b=7, char z='*'为缺省参数，选项C的调用testDefaulParam(5,'#');违反了缺省参数从右向左连续匹配的规则，导致不合法 |
| XDU_CPP_A_C_A_S01_Q05 | course_cpp | 函数重载 | primary | correct | 题干明确要求选择正确重载的函数，正确选项C通过改变参数类型实现了重载，核心考点是函数重载的规则（参数列表不同，返回类型无关） |
| XDU_CPP_A_C_A_S01_Q06 | course_cpp | 引用 | primary | correct | 题干明确考察引用的正确声明方式，正确选项A为int &x=a;，涉及引用的定义与初始化规则。 |
| XDU_CPP_A_C_A_S01_Q07 | course_cpp | 内联函数 | primary | correct | 题干要求加快执行速度，内联函数通过减少函数调用开销实现加速，正确选项为内联函数。 |
| XDU_CPP_A_C_A_S01_Q08 | course_cpp | 访问控制 | primary | correct | 题干考查类中成员默认访问权限，选项C（私有）与D（公用）直接对比，核心知识点是访问控制规则 |
| XDU_CPP_A_C_A_S01_Q09 | course_cpp | 构造方法与析构方法 | primary | correct | 题干明确询问调用了多少次构造函数，核心是构造函数的调用次数。 |
| XDU_CPP_A_C_A_S01_Q09 | course_cpp | 数组 | secondary | correct | 语句定义了一个包含3个元素的数组，导致构造函数被调用3次。 |
| XDU_CPP_A_C_A_S01_Q10 | course_cpp | 构造方法与析构方法 | primary | correct | 正确选项B直接陈述构造函数可以定义多个，析构函数只能定义一个，这是构造方法与析构方法的核心特性。 |
| XDU_CPP_A_C_A_S01_Q11 | course_cpp | 常成员 | primary | correct | 题干明确指出print()是类的常成员函数，正确选项A是常成员函数的正确声明形式 |
| XDU_CPP_A_C_A_S01_Q12 | course_cpp | 访问控制 | primary | correct | 题目考查公用继承和私有继承下基类成员在派生类中的可访问性变化，核心是访问控制规则 |
| XDU_CPP_A_C_A_S01_Q13 | course_cpp | 虚继承 | primary | correct | 题干直接询问设置虚基类的目的，虚继承的核心作用正是消除多重继承中的二义性，与正确选项B一致。 |
| XDU_CPP_A_C_A_S01_Q14 | course_cpp | 父类与子类 | primary | correct | 赋值兼容规则由基类与派生类的方向关系决定。 |
| XDU_CPP_A_C_A_S01_Q15 | course_cpp | 动态绑定 | primary | correct | 题干直接考查虚函数的特性，而虚函数是实现动态绑定的核心机制；正确选项C描述的是派生类中虚函数自动继承基类虚函数的特性，属于动态绑定的重要规则。 |
| XDU_CPP_A_C_A_S01_Q16 | course_cpp | 友元 | primary | correct | 题干直接提及友元，选项围绕友元函数、友元类及友元关系继承展开，核心考察友元特性 |
| XDU_CPP_A_C_A_S01_Q17 | course_cpp | 静态成员 | primary | correct | 题干直接考查静态数据成员的概念与特性，正确选项C描述静态数据成员不是所有对象所共用的，正是对静态成员共享性的错误理解，因此静态成员是本题的核心知识点。 |
| XDU_CPP_A_C_A_S01_Q18 | course_cpp | 操作符重载 | primary | correct | 题干明确要求将重载运算符表达式转换为运算符函数调用格式，核心是理解重载运算符的友元函数调用约定 |
| XDU_CPP_A_C_A_S01_Q18 | course_cpp | 友元 | secondary | correct | 题干指明“++”和“*”都是重载的友元运算符，决定了调用形式中操作数为参数而非this指针 |
| XDU_CPP_A_C_A_S01_Q19 | course_cpp | 泛型与模板 | primary | correct | 题干直接询问模板的正确声明，正确选项C展示了多个模板参数的正确语法，核心考点是模板声明规则，属于泛型与模板知识点。 |
| XDU_CPP_A_C_A_S01_Q20 | course_cpp | 友元 | primary | correct | 正确选项C.友元函数不是类的成员函数，友元是本题的核心考点 |
| XDU_CPP_COLLECTION_C_S01_Q02 | course_cpp | 引用 | primary | correct | 题干明确考查引用的声明和初始化规则，正确选项A展示了引用必须初始化为变量，错误选项B、C、D分别对应引用不能绑定常量、必须初始化、类型须匹配等规则。 |
| XDU_CPP_COLLECTION_C_S01_Q04 | course_cpp | 函数重载 | primary | correct | 题干明确提及'重载函数'，且选项涉及重载函数调用的依据（参数类型、参数个数、函数名称、返回值类型），正确选项指出返回值类型不能作为依据，直接考察函数重载的判定规则。 |
| XDU_CPP_COLLECTION_C_S01_Q07 | course_cpp | 构造方法与析构方法 | primary | correct | 题目考查析构函数的特性（不能有参数、只能一个、无返回值等），正确选项B指出析构函数不能有形参，与构造函数不同，核心知识点是析构函数的定义与规则。 |
| XDU_CPP_COLLECTION_C_S01_Q08 | course_cpp | 访问控制 | primary | correct | 题目询问类定义中允许对象无限制存取的部分，正确答案为public部分，直接考察访问控制的概念。 |
| XDU_CPP_COLLECTION_C_S01_Q09 | course_cpp | 常成员 | primary | correct | 题干直接提问“常数据成员”，选项围绕常数据成员定义、初始化、更新规则，核心考点是常数据成员的特性 |
| XDU_CPP_COLLECTION_C_S01_Q09 | course_cpp | 构造方法与析构方法 | secondary | correct | 常数据成员必须通过构造函数的成员初始化列表进行初始化，选项C和D涉及初始化方式，属于构造函数相关规则 |
| XDU_CPP_COLLECTION_C_S01_Q10 | course_cpp | 对象的动态创建与销毁 | primary | correct | 题干明确使用delete运算符删除动态对象，核心考察动态对象销毁的语义顺序 |
| XDU_CPP_COLLECTION_C_S01_Q10 | course_cpp | 构造方法与析构方法 | secondary | correct | 正确选项指出先调用析构函数再释放内存，涉及析构函数的调用时机 |
| XDU_CPP_COLLECTION_C_S01_Q11 | course_cpp | 访问控制 | primary | correct | 题目考查派生类对象在类外访问基类成员的可访问性，核心是继承中的访问权限规则，正确选项为公用继承的公用成员 |
| XDU_CPP_COLLECTION_C_S01_Q11 | course_cpp | 父类与子类 | secondary | correct | 题目涉及派生类对象访问基类成员，需要理解继承关系中的父类与子类概念 |
| XDU_CPP_COLLECTION_C_S01_Q12 | course_cpp | 访问控制 | primary | correct | 题干考查公用继承下派生类对象对基类成员的访问权限，选项C不正确的原因即在于派生类对象不能直接访问基类的私有成员，核心知识点为访问控制。 |
| XDU_CPP_COLLECTION_C_S01_Q12 | course_cpp | 父类与子类 | secondary | correct | 题目涉及公用继承下派生类与基类的关系，理解父类与子类的继承关系是分析选项的基础。 |
| XDU_CPP_COLLECTION_C_S01_Q14 | course_cpp | 动态绑定 | primary | correct | 题干明确询问实现动态多态性的机制，正确选项‘虚函数’是动态绑定的基础，且候选知识点‘动态绑定’的规则证据直接匹配题干和正确选项。 |
| XDU_CPP_COLLECTION_C_S01_Q15 | course_cpp | 构造方法与析构方法 | primary | correct | 题目考查构造函数不能为虚函数，辨析析构函数与构造函数在虚函数声明上的区别，选项B正确对应此知识点 |
| XDU_CPP_COLLECTION_C_S01_Q16 | course_cpp | 抽象类 | primary | correct | 题干：如果一个类至少有一个纯虚函数，那么就称该类为抽象类。正确选项为抽象类，考查抽象类的定义。 |
| XDU_CPP_COLLECTION_C_S01_Q18 | course_cpp | 操作符重载 | primary | correct | 题目考察C++中哪些运算符不能被重载，正确选项为::，属于操作符重载的限制规则。 |
| XDU_CPP_COLLECTION_C_S01_Q19 | course_cpp | 泛型与模板 | primary | correct | 题干明确提及‘模板的使用’，且题目核心考察类模板实例化的概念 |
| XDU_CPP_COLLECTION_C_S01_Q19 | course_cpp | 实例化 | secondary | correct | 题干中出现‘实例化’，是模板使用的具体过程 |
| XDU_CPP_COLLECTION_C_S01_Q20 | course_cpp | 拷贝构造函数 | primary | correct | 题干明确要求选择拷贝构造函数的正确声明语句，正确选项C使用引用参数，这是拷贝构造函数的核心语法规则。 |
| XDU_JAVA_2019_SHORT_Q01 | course_java | 类 | primary | correct | 题目直接考查类的概念。 |
| XDU_JAVA_2019_SHORT_Q01 | course_java | 对象 | secondary | correct | 题目同时要求说明对象。 |
| XDU_JAVA_2019_SHORT_Q01 | course_java | 引用 | secondary | correct | 题目同时要求说明对象引用。 |
| XDU_JAVA_2019_SHORT_Q02 | course_java | 动态绑定 | primary | correct | 运行时多态的核心机制是动态绑定。 |
| XDU_JAVA_2019_SHORT_Q02 | course_java | 方法重写 | secondary | correct | 题目答案明确包含方法重写。 |
| XDU_JAVA_2019_SHORT_Q02 | course_java | 向上转型 | secondary | correct | 题目答案明确包含向上转型。 |
| XDU_JAVA_2019_READ_Q01 | course_java | 数组 | primary | correct | 程序遍历并读取数组元素。 |
| XDU_JAVA_2019_READ_Q01 | course_java | for循环 | secondary | correct | 使用 for 循环遍历数组。 |
| XDU_JAVA_2019_READ_Q01 | course_java | if语句 | secondary | correct | 使用 if 判断偶数。 |
| XDU_JAVA_2019_READ_Q02 | course_java | 静态成员 | primary | correct | 题目核心是静态变量和静态初始化块只初始化一次。 |
| XDU_JAVA_2019_READ_Q02 | course_java | 实例化 | secondary | correct | 两次创建对象用于比较实例成员状态。 |
| XDU_JAVA_2019_READ_Q03 | course_java | 动态绑定 | primary | correct | 父类引用调用子类重写方法体现动态绑定。 |
| XDU_JAVA_2019_READ_Q03 | course_java | 方法重写 | secondary | correct | Cat 重写 Animal.eat。 |
| XDU_JAVA_2019_READ_Q03 | course_java | 向上转型 | secondary | correct | Animal 引用指向 Cat 对象体现向上转型。 |
| XDU_JAVA_2019_FILL_Q01 | course_java | 构造方法与析构方法 | primary | correct | 题目要求补全子类构造方法。 |
| XDU_JAVA_2019_FILL_Q01 | course_java | 属性与方法 | secondary | correct | 答案完成 name 属性赋值。 |
| XDU_JAVA_2019_FILL_Q02 | course_java | 方法重写 | primary | correct | Cat 实现父类抽象 eat 方法。 |
| XDU_JAVA_2019_FILL_Q02 | course_java | 属性与方法 | secondary | correct | 方法修改对象 weight 属性。 |
| XDU_JAVA_2019_FILL_Q03 | course_java | 接口 | primary | correct | 题目明确要求实现 Runner 接口方法。 |
| XDU_JAVA_2019_FILL_Q03 | course_java | 方法重写 | secondary | correct | 实现接口方法属于方法实现/重写。 |
| XDU_JAVA_2019_FILL_Q03 | course_java | 输入输出 | secondary | correct | 方法通过 println 输出信息。 |
| XDU_JAVA_2019_FILL_Q04 | course_java | for循环 | primary | correct | 答案使用增强 for 循环遍历数组。 |
| XDU_JAVA_2019_FILL_Q04 | course_java | 动态绑定 | secondary | correct | 对 Animal 引用调用 eat 会触发动态绑定。 |
| XDU_JAVA_2019_FILL_Q04 | course_java | 数组 | secondary | correct | 遍历对象数组。 |
| XDU_JAVA_2018_FILL_Q01 | course_java | 属性与方法 | primary | correct | 题目要求实现对象信息方法。 |
| XDU_JAVA_2018_FILL_Q01 | course_java | 参数与返回值 | secondary | correct | 方法构造并返回字符串结果。 |
| XDU_JAVA_2018_FILL_Q01 | course_java | 字符串 | secondary | correct | 返回值是格式化字符串。 |
| XDU_JAVA_2018_FILL_Q02 | course_java | 方法重写 | primary | correct | Dog 重写抽象 raise 方法。 |
| XDU_JAVA_2018_FILL_Q02 | course_java | 属性与方法 | secondary | correct | 方法更新 weight 属性。 |
| XDU_JAVA_2018_FILL_Q03 | course_java | 方法重写 | primary | correct | Cat 重写抽象 raise 方法。 |
| XDU_JAVA_2018_FILL_Q03 | course_java | 属性与方法 | secondary | correct | 方法更新 weight 属性。 |
| XDU_JAVA_2018_FILL_Q04 | course_java | 列表 | primary | correct | 题目遍历 List<Pet> 列表。 |
| XDU_JAVA_2018_FILL_Q04 | course_java | for循环 | secondary | correct | 答案使用增强 for 循环。 |
| XDU_JAVA_2018_FILL_Q04 | course_java | 动态绑定 | secondary | correct | 对 Pet 引用调用 raise 体现动态绑定。 |
