import tensorflow as tf
from tensorflow.contrib import rnn
import numpy as np
from nl_w2v import DataPrepare
import argparse
import random
from sklearn.metrics import f1_score
from sklearn.preprocessing import Binarizer

config = tf.ConfigProto()
config.gpu_options.allow_growth = True



def get_glove(GloVe):
    d = {}
    dict_dim = 200
    with open(GloVe,'r') as f:
        for l in f:
            tmp = l.strip().split()
            d[tmp[0]] = [float(dim) for dim in tmp[1:]]
    n = np.zeros(dict_dim)
    n[dict_dim-1] = 999
    d['<unk>'] = n
    d['Empty'] = np.zeros(dict_dim)
    add_s = ['let','that','it','there','here','how','he','she','what']
    add_nt = ['do','did','were','have','does','would','was','has','should','is','are']
    add_re = ['we','they','you']
    add_ha = ['i','who','they','you','we']
    add_am = ['i']
    add_will = ['you','he','i','she','we','there','it','they']
    add_d = ['you','i','they','that','we']
    prefix = [add_s,add_nt,add_re,add_ha,add_am,add_will,add_d]
    syms = ['\'s','not','are','have','am','will','would']
    short = ['\'s','n\'t','\'re','\'ve','\'m','\'ll','\'d']
    for i in range(len(prefix)):
        for word in prefix[i]:
            d[word+short[i]] = np.add(d[word],d[syms[i]])
    d['won\'t'] = np.add(d['will'],d['not'])
    d['can\'t'] = np.add(d['can'],d['not'])
    return d

Glove = "../GloVe/glove.6B.200d.txt"
glove_dict = get_glove(Glove)
path = ["../GloVe/glove.6B.200d.txt" , "./Data/train/seq.in" , "./Data/train/seq.out" , "./Data/train/intent","./Data/train/info"]
t_path = ["../GloVe/glove.6B.200d.txt" , "./Data/test/seq.in" , "./Data/test/seq.out" , "./Data/test/intent","./Data/test/info"]

Data = DataPrepare(path,glove_dict)
t_data = DataPrepare(t_path,glove_dict)

epoc = 30
learning_rate = 0.001
batch_size = 128
w2v_l = 200

num_word = Data.maxlength
num_hidden_layer = 128
num_sentences = 6

# guide_in = tf.placeholder('float', [None, num_word, 200])
# tourist_in = tf.placeholder('float', [None, num_word, 200])
nl_in = tf.placeholder('float',[None,num_word,200])
sap_in = tf.placeholder('float',[None,num_sentences,4*num_hidden_layer])
# tourist_sap_in = tf.placeholder('float', [None, num_sentences, 4*num_hidden_layer])
# guide_sap_in = tf.placeholder('float', [None, num_sentences, 4*num_hidden_layer])
sap_y = tf.placeholder('float',[None, 27])

#define weights
weights = {
    'sap_weight': tf.Variable(tf.random_normal([4*num_hidden_layer, 27]), name='sap_weight')
}
biases = {
    'sap_biase' : tf.Variable(tf.random_normal([27]),name='sap_biase')
}


def nl_birnn(x,scope):
    x = tf.unstack(x, num_word, 1)
    lstm_fw_cell = rnn.BasicLSTMCell(num_hidden_layer, forget_bias=1.0, activation=tf.tanh)
    lstm_bw_cell = rnn.BasicLSTMCell(num_hidden_layer, forget_bias=1.0, activation=tf.tanh)
    with tf.variable_scope(scope):
        outputs, fw, bw = rnn.static_bidirectional_rnn(lstm_fw_cell,lstm_bw_cell,x,dtype=tf.float32)
    fw = tf.concat([fw[0],fw[1]],axis=-1)
    bw = tf.concat([bw[0],bw[1]],axis=-1)
    final_state = tf.concat([fw,bw],axis=-1)
    return final_state
    # return outputs[-1]

filter_sizes = [2,3,4]
filter_depth = 128
def nl_cnn(x, scope):
    with tf.variable_scope(scope):
        pooled_outputs = list()
        for idx, filter_size in enumerate(filter_sizes):
            # convolution layer
            h = tf.layers.conv1d(x, filter_depth, filter_size, activation=tf.nn.relu, kernel_initializer=tf.random_normal_initializer, bias_initializer=tf.random_normal_initializer)
            # max over time pooling
            pooled = tf.layers.max_pooling1d(h, (Data.maxlength-filter_size+1), 1)
            pooled_outputs.append(pooled)
        num_filters_total = filter_depth * len(filter_sizes)
        h_pool_flat = tf.squeeze(tf.concat(pooled_outputs, axis=2), axis=1)
        h_drop = tf.nn.dropout(h_pool_flat, 0.75)
        dense_h = tf.layers.dense(inputs=h_drop, units=512, kernel_initializer=tf.random_normal_initializer, bias_initializer=tf.random_normal_initializer)
        
        return dense_h

nl_out = nl_cnn(nl_in,'nl')

def sap_birnn(x,scope):
    x = tf.unstack(x, num_sentences, 1)
    lstm_fw_cell = rnn.BasicLSTMCell(num_hidden_layer, forget_bias=1.0, activation=tf.tanh)
    lstm_bw_cell = rnn.BasicLSTMCell(num_hidden_layer, forget_bias=1.0, activation=tf.tanh)
    with tf.variable_scope(scope):
        outputs, fw, bw = rnn.static_bidirectional_rnn(lstm_fw_cell,lstm_bw_cell,x,dtype=tf.float32)
    fw = tf.concat([fw[0],fw[1]],axis=-1)
    bw = tf.concat([bw[0],bw[1]],axis=-1)
    final_state = tf.concat([fw,bw],axis=-1)
    return final_state

sap_out = sap_birnn(sap_in,"directsix_sap")

sap_pred = tf.matmul(sap_out,weights['sap_weight']) + biases['sap_biase']
_sap_pred = tf.sigmoid(sap_pred)

sap_cost = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(labels=sap_y,logits=sap_pred))
sap_optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate).minimize(sap_cost)

init = tf.global_variables_initializer()

def toone(logits):
    # print (len(logits),len(logits[0]),"logit")
    for i in range(len(logits)):
        max_major = 0
        max_value = 0
        for j in range(len(Data.intentdict[0])):
            if logits[i][j] >= 0.5:
                max_major = j
                max_value = logits[i][j]
                logits[i][j] = 1
            elif logits[i][j] > max_value:
                max_major = j
                max_value = logits[i][j]
                logits[i][j] = 0
            else:
                logits[i][j] = 0
        logits[i][max_major] = 1
        max_minor = 0
        max_value = 0
        for j in range(len(Data.intentdict[0]),len(Data.intentdict[0])+len(Data.intentdict[1])):
            if logits[i][j] >= 0.5:
                max_minor = j
                max_value = logits[i][j]
                logits[i][j] = 1
            elif logits[i][j] > max_value:
                max_minor = j
                max_value = logits[i][j]
                logits[i][j] = 0
            else:
                logits[i][j] = 0
        logits[i][max_minor] = 1
    return logits

def preprocess(logits,labels):
    logits = toone(logits)
    bin = Binarizer(threshold=0.2)
    for i in range(len(logits)):
        if logits[i][Data.intentdict[1]['none']] > 0.5 and labels[i][Data.intentdict[1]['none']] > 0.5:
            logits[i][Data.intentdict[1]['none']] = int(0)
            labels[i][Data.intentdict[1]['none']] = int(0)
    logits = bin.fit_transform(logits)
    labels = bin.fit_transform(labels)
    return logits.flatten(),labels.flatten()

def intout(fp,pred_out):
    first = 1
    for i in range(len(pred_out)):
        if pred_out[i] > 0.5 and first == 1:
            fp.write(Data.rev_intentdict[i])
            first = 0
        elif pred_out[i] > 0.5:
            fp.write("-"+Data.rev_intentdict[i])
    fp.write('\n')

with tf.Session(config=config) as sess:
    tf.set_random_seed(20)
    np.random.seed(20)
    sess.run(init)
    iterations = 0
    best = 0.001
    while iterations < epoc:
        lol = []
        lal = []
        for step,(batch_i,batch_nl) in enumerate(Data.get_batch(batch_size)):
            batch_nl = np.transpose(batch_nl,(1,0,2,3))
            batch_nl_in = batch_nl[0:6]
            batch_nl_out = []
            for i in range(len(batch_nl_in)):
                o = sess.run(nl_out,feed_dict={nl_in:batch_nl_in[i]})
                batch_nl_out.append(o)
            #6xbatchx2outlayer
            batch_nl_out = np.transpose(batch_nl_out,(1,0,2))
            batch_i = np.transpose(batch_i,(1,0,2))
            system_action = batch_i[-1]
            _,c,p = sess.run([sap_optimizer,sap_cost,_sap_pred],feed_dict={sap_in:batch_nl_out,sap_y:system_action})
            # print (c)
            log,lab = preprocess(p,system_action)
            lol = np.concatenate((lol,log),axis=0)
            lal = np.concatenate((lal,lab),axis=0)
            if step % 50 == 0 and step != 0:
                logit_list = []
                label_list = []
                # f = open('./saptwoout.txt','w')
                for test_step,(test_batch_i,test_batch_nl) in enumerate(t_data.get_batch(batch_size)):
                    test_batch_nl = np.transpose(test_batch_nl,(1,0,2,3))
                    test_batch_nl = test_batch_nl[0:6]
                    test_batch_out = []
                    for i in range(len(test_batch_nl)):
                        o = sess.run(nl_out,feed_dict={nl_in:test_batch_nl[i]})
                        test_batch_out.append(o)
                    test_batch_out = np.transpose(test_batch_out,(1,0,2))

                    test_batch_i = np.transpose(test_batch_i,(1,0,2))
                    test_system_action = test_batch_i[-1]
                    # print (test_batch_i.shape,test_system_action.shape,"shape")
                    system_action_prediction = sess.run(_sap_pred,feed_dict={sap_in:test_batch_out,sap_y:test_system_action})
                    logit,label = preprocess(system_action_prediction,test_system_action)
                    # intout(f,logit)
                    logit_list = np.concatenate((logit_list,logit),axis=0)
                    label_list = np.concatenate((label_list,label),axis=0)
                test_score = f1_score(logit_list,label_list,average='binary')
                if test_score > best:
                    best = test_score
                print (iterations,test_score,"testing")
        print (iterations,f1_score(lol,lal,average='binary'),'training')
        iterations += 1
    print ("best",best)
