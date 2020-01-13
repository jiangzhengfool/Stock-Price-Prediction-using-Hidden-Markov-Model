import numpy as np
from abc import ABCMeta, abstractmethod


class _BaseHMM:
    """
    n_state : 隐藏状态的数目
    n_iter : 迭代次数
    x_size : 观测值维度
    start_prob : 初始概率
    transmat_prob : 状态转换概率
    """

    __metaclass__ = ABCMeta  # 虚类声明

    def __init__(self, n_state=1, x_size=1, iter=20):
        self.n_state = n_state
        self.x_size = x_size
        self.start_prob = np.ones(n_state) * (1.0 / n_state)  # 初始状态概率
        self.transmat_prob = np.ones((n_state, n_state)) * (1.0 / n_state)  # 状态转换概率矩阵
        self.trained = False  # 是否需要重新训练
        self.n_iter = iter  # EM训练的迭代次数

    # 初始化发射参数
    @abstractmethod
    def _init(self, X):
        pass

    # 虚函数：返回发射概率
    @abstractmethod
    def emit_prob(self, x):  # 求x在状态k下的发射概率 P(X|Z)
        return np.array([0])

    # 虚函数
    @abstractmethod
    def generate_x(self, z):  # 根据隐状态生成观测值x p(x|z)
        return np.array([0])

    # 虚函数：发射概率的更新
    @abstractmethod
    def emit_prob_updated(self, X, post_state):
        pass

    # 通过HMM生成序列
    def generate_seq(self, seq_length):
        X = np.zeros((seq_length, self.x_size))
        Z = np.zeros(seq_length)
        Z_pre = np.random.choice(self.n_state, 1, p=self.start_prob)  # 采样初始状态
        X[0] = self.generate_x(Z_pre)  # 采样得到序列第一个值
        Z[0] = Z_pre

        for i in range(seq_length):
            if i == 0:
                continue
            # P(Zn+1)=P(Zn+1|Zn)P(Zn)
            Z_next = np.random.choice(
                self.n_state, 1, p=self.transmat_prob[Z_pre, :][0]
            )
            Z_pre = Z_next
            # P(Xn+1|Zn+1)
            X[i] = self.generate_x(Z_pre)
            Z[i] = Z_pre

        return X, Z

    # 估计序列X出现的概率
    def X_prob(self, X, Z_seq=np.array([])):
        # 状态序列预处理
        # 判断是否已知隐藏状态
        X_length = len(X)
        if Z_seq.any():
            Z = np.zeros((X_length, self.n_state))
            for i in range(X_length):
                Z[i][int(Z_seq[i])] = 1
        else:
            Z = np.ones((X_length, self.n_state))
        # 向前向后传递因子
        _, c = self.forward(X, Z)  # P(x,z)
        # 序列的出现概率估计
        prob_X = np.sum(np.log(c))  # P(X)
        return prob_X

    # 已知当前序列预测未来（下一个）观测值的概率
    def predict_next_prob(self, X, x_next, Z_seq=np.array([]), istrain=True):
        if self.trained == False or istrain == False:  # 需要根据该序列重新训练
            self.train(X)

        X_length = len(X)
        if Z_seq.any():
            Z = np.zeros((X_length, self.n_state))
            for i in range(X_length):
                Z[i][int(Z_seq[i])] = 1
        else:
            Z = np.ones((X_length, self.n_state))
        # 向前向后传递因子
        alpha, _ = self.forward(X, Z)  # P(x,z)
        prob_x_next = self.emit_prob(np.array([x_next])) * np.dot(
            alpha[X_length - 1], self.transmat_prob
        )
        return prob_x_next

    def decode(self, X, istrain=True):
        """
        利用维特比算法，已知序列求其隐藏状态值
        :param X: 观测值序列
        :param istrain: 是否根据该序列进行训练
        :return: 隐藏状态序列
        """
        if self.trained == False or istrain == False:  # 需要根据该序列重新训练
            self.train(X)

        X_length = len(X)  # 序列长度
        state = np.zeros(X_length)  # 隐藏状态

        pre_state = np.zeros((X_length, self.n_state))  # 保存转换到当前隐藏状态的最可能的前一状态
        max_pro_state = np.zeros((X_length, self.n_state))  # 保存传递到序列某位置当前状态的最大概率

        _, c = self.forward(X, np.ones((X_length, self.n_state)))
        max_pro_state[0] = self.emit_prob(X[0]) * self.start_prob * (1 / c[0])  # 初始概率

        # 前向过程
        for i in range(X_length):
            if i == 0:
                continue
            for k in range(self.n_state):
                prob_state = (
                    self.emit_prob(X[i])[k]
                    * self.transmat_prob[:, k]
                    * max_pro_state[i - 1]
                )
                max_pro_state[i][k] = np.max(prob_state) * (1 / c[i])
                pre_state[i][k] = np.argmax(prob_state)

        # 后向过程
        state[X_length - 1] = np.argmax(max_pro_state[X_length - 1, :])
        for i in reversed(range(X_length)):
            if i == X_length - 1:
                continue
            state[i] = pre_state[i + 1][int(state[i + 1])]

        return state

    # 针对于多个序列的训练问题
    def train_batch(self, X, Z_seq=list()):
        # 针对于多个序列的训练问题，其实最简单的方法是将多个序列合并成一个序列，而唯一需要调整的是初始状态概率
        # 输入X类型：list(array)，数组链表的形式
        # 输入Z类型: list(array)，数组链表的形式，默认为空列表（即未知隐状态情况）
        self.trained = True
        X_num = len(X)  # 序列个数
        self._init(self.expand_list(X))  # 发射概率的初始化

        # 状态序列预处理，将单个状态转换为1-to-k的形式
        # 判断是否已知隐藏状态
        if Z_seq == list():
            Z = []  # 初始化状态序列list
            for n in range(X_num):
                Z.append(list(np.ones((len(X[n]), self.n_state))))
        else:
            Z = []
            for n in range(X_num):
                Z.append(np.zeros((len(X[n]), self.n_state)))
                for i in range(len(Z[n])):
                    Z[n][i][int(Z_seq[n][i])] = 1

        for e in range(self.n_iter):  # EM步骤迭代
            # 更新初始概率过程
            #  E步骤
            print("iter: ", e)
            b_post_state = []  # 批量累积：状态的后验概率，类型list(array)
            b_post_adj_state = np.zeros(
                (self.n_state, self.n_state)
            )  # 批量累积：相邻状态的联合后验概率，数组
            b_start_prob = np.zeros(self.n_state)  # 批量累积初始概率
            for n in range(X_num):  # 对于每个序列的处理
                X_length = len(X[n])
                alpha, c = self.forward(X[n], Z[n])  # P(x,z)
                beta = self.backward(X[n], Z[n], c)  # P(x|z)

                post_state = alpha * beta / np.sum(alpha * beta)  # 归一化！
                b_post_state.append(post_state)
                post_adj_state = np.zeros((self.n_state, self.n_state))  # 相邻状态的联合后验概率
                for i in range(X_length):
                    if i == 0:
                        continue
                    if c[i] == 0:
                        continue
                    post_adj_state += (
                        (1 / c[i])
                        * np.outer(alpha[i - 1], beta[i] * self.emit_prob(X[n][i]))
                        * self.transmat_prob
                    )

                if np.sum(post_adj_state) != 0:
                    post_adj_state = post_adj_state / np.sum(post_adj_state)  # 归一化！
                b_post_adj_state += post_adj_state  # 批量累积：状态的后验概率
                b_start_prob += b_post_state[n][0]  # 批量累积初始概率

            # M步骤，估计参数，最好不要让初始概率都为0出现，这会导致alpha也为0
            b_start_prob += 0.001 * np.ones(self.n_state)
            self.start_prob = b_start_prob / np.sum(b_start_prob)
            b_post_adj_state += 0.001
            for k in range(self.n_state):
                if np.sum(b_post_adj_state[k]) == 0:
                    continue
                self.transmat_prob[k] = b_post_adj_state[k] / np.sum(
                    b_post_adj_state[k]
                )

            self.emit_prob_updated(self.expand_list(X), self.expand_list(b_post_state))

    def expand_list(self, X):
        # 将list(array)类型的数据展开成array类型
        C = []
        for i in range(len(X)):
            C += list(X[i])
        return np.array(C)

    # 针对于单个长序列的训练
    def train(self, X, Z_seq=np.array([])):
        # 输入X类型：array，数组的形式
        # 输入Z类型: array，一维数组的形式，默认为空列表（即未知隐状态情况）
        self.trained = True
        X_length = len(X)
        self._init(X)

        # 状态序列预处理
        # 判断是否已知隐藏状态
        if Z_seq.any():
            Z = np.zeros((X_length, self.n_state))
            for i in range(X_length):
                Z[i][int(Z_seq[i])] = 1
        else:
            Z = np.ones((X_length, self.n_state))

        for e in range(self.n_iter):  # EM步骤迭代
            # 中间参数
            print(e, " iter")
            # E步骤
            # 向前向后传递因子
            alpha, c = self.forward(X, Z)  # P(x,z)
            beta = self.backward(X, Z, c)  # P(x|z)

            post_state = alpha * beta
            post_adj_state = np.zeros((self.n_state, self.n_state))  # 相邻状态的联合后验概率
            for i in range(X_length):
                if i == 0:
                    continue
                if c[i] == 0:
                    continue
                post_adj_state += (
                    (1 / c[i])
                    * np.outer(alpha[i - 1], beta[i] * self.emit_prob(X[i]))
                    * self.transmat_prob
                )

            # M步骤，估计参数
            self.start_prob = post_state[0] / np.sum(post_state[0])
            for k in range(self.n_state):
                self.transmat_prob[k] = post_adj_state[k] / np.sum(post_adj_state[k])

            self.emit_prob_updated(X, post_state)

    # 求向前传递因子
    def forward(self, X, Z):
        X_length = len(X)
        alpha = np.zeros((X_length, self.n_state))  # P(x,z)
        alpha[0] = self.emit_prob(X[0]) * self.start_prob * Z[0]  # 初始值
        # 归一化因子
        c = np.zeros(X_length)
        c[0] = np.sum(alpha[0])
        alpha[0] = alpha[0] / c[0]
        # 递归传递
        for i in range(X_length):
            if i == 0:
                continue
            alpha[i] = (
                self.emit_prob(X[i]) * np.dot(alpha[i - 1], self.transmat_prob) * Z[i]
            )
            c[i] = np.sum(alpha[i])
            if c[i] == 0:
                continue
            alpha[i] = alpha[i] / c[i]

        return alpha, c

    # 求向后传递因子
    def backward(self, X, Z, c):
        X_length = len(X)
        beta = np.zeros((X_length, self.n_state))  # P(x|z)
        beta[X_length - 1] = np.ones((self.n_state))
        # 递归传递
        for i in reversed(range(X_length)):
            if i == X_length - 1:
                continue
            beta[i] = (
                np.dot(beta[i + 1] * self.emit_prob(X[i + 1]), self.transmat_prob.T)
                * Z[i]
            )
            if c[i + 1] == 0:
                continue
            beta[i] = beta[i] / c[i + 1]

        return beta
